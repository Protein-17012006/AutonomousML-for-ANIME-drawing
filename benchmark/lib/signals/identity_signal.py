"""Deterministic visual-integrity signal (DINOv2 temporal feature stability).

Companion to `motion_signal.py`. The identity-tuned VLM is blind to SUBTLE
within-shot degradation — fine smear / face-proportion wobble that stays "the
same character" yet is a real generation defect. suite_identity re-audit
(2026-06-17): 21/42 clips the identity-VLM passed carry visible distortion on a
second `artifact` axis; an artifact-prompt VLM arm did NOT help (resolution
wall), so the lever is this signal. It quantifies degradation the VBench
`subject_consistency` way: per-frame DINOv2 features, then temporal instability.

v2 adds three things over plain whole-frame CLS cosine, targeting the two real
misses reconcile left (id002 smooth smear, id040 localized melt):
  - SMOOTH-DRIFT metrics (diameter, path_len) — a gradual smear accumulates total
    wander even when each consecutive step is small (worst_jump misses it).
  - PATCH-LOCALISED instability (patch_jump_p90/p99) — a melt confined to part of
    the frame spikes some patches even if the whole-frame CLS stays stable, and a
    static background dilutes whole-frame CLS but not the patch percentile.
  - MASKED-CLS via DINO-PCA foreground (no external segmenter): the first PCA
    component of the patch tokens separates character from background; recomputing
    CLS-like instability over foreground patches only suppresses background-pan
    false positives. Pure-numpy, so it needs no seg model on the box.

It is a MAGNITUDE estimator meant to ENSEMBLE with the VLM (which adjudicates
intended-motion-vs-defect), NOT a standalone classifier. Run on the box:
    ~/anime-ft-venv/bin/python -m benchmark.lib.signals.identity_signal \\
        --clips <dir-of-clip-subdirs> --out signal.json
"""
from __future__ import annotations

import argparse
import json
import os

_FRAME_EXTS = (".png", ".jpg", ".jpeg", ".webp")


def _frame_paths(clip_dir: str) -> list[str]:
    names = [n for n in sorted(os.listdir(clip_dir))
             if n.lower().endswith(_FRAME_EXTS)]
    return [os.path.join(clip_dir, n) for n in names]


def _load_dino(model_id: str, device: str, crop: int):
    """Lazy DINOv2 load (torch + transformers only exist on the box). crop sets a
    square input so the patch grid is dense (crop/14 per side) for spatial metrics."""
    import torch  # noqa: F401
    from transformers import AutoImageProcessor, AutoModel
    proc = AutoImageProcessor.from_pretrained(
        model_id, size={"shortest_edge": crop},
        crop_size={"height": crop, "width": crop})
    model = AutoModel.from_pretrained(model_id).to(device).eval()
    return proc, model


def _features(paths, proc, model, device, batch):
    """Return (cls [n,d], patches [n,P,d]) L2-normalised per vector."""
    import torch
    import torch.nn.functional as F
    from PIL import Image
    cls_all, pat_all = [], []
    for i in range(0, len(paths), batch):
        imgs = [Image.open(p).convert("RGB") for p in paths[i:i + batch]]
        inputs = proc(images=imgs, return_tensors="pt").to(device)
        with torch.no_grad():
            out = model(**inputs)
        h = out.last_hidden_state                      # [b, 1+P, d]
        cls_all.append(F.normalize(h[:, 0], dim=-1).cpu())
        pat_all.append(F.normalize(h[:, 1:], dim=-1).cpu())
    import numpy as np
    return (torch.cat(cls_all).numpy(),
            np.ascontiguousarray(torch.cat(pat_all).numpy()))


def _cls_metrics(feats) -> dict:
    import numpy as np
    n = len(feats)
    if n < 2:
        return {"instability": 0.0, "worst_jump": 0.0, "drift_from_first": 0.0,
                "spread": 0.0, "diameter": 0.0, "path_len": 0.0}
    consec = np.sum(feats[:-1] * feats[1:], axis=1)
    first = np.sum(feats * feats[0], axis=1)
    centroid = feats.mean(axis=0)
    cn = centroid / (np.linalg.norm(centroid) + 1e-8)
    spread = np.sum(feats * cn, axis=1)
    gram = feats @ feats.T                              # pairwise cos
    diameter = float((1.0 - gram).max())               # widest wander (smooth-safe)
    return {
        "instability": float(1.0 - consec.mean()),
        "worst_jump": float(1.0 - consec.min()),
        "drift_from_first": float((1.0 - first).max()),
        "spread": float((1.0 - spread).mean()),
        "diameter": diameter,
        "path_len": float((1.0 - consec).sum()),        # cumulative path length
    }


def _patch_metrics(patches) -> dict:
    """patches [n,P,d] L2-normed. Localised temporal instability per patch."""
    import numpy as np
    n, P, _ = patches.shape
    if n < 2:
        return {"patch_jump_p90": 0.0, "patch_jump_p99": 0.0,
                "patch_drift_p90": 0.0}
    consec = 1.0 - np.sum(patches[:-1] * patches[1:], axis=2)   # [n-1, P]
    patch_max_jump = consec.max(axis=0)                          # [P]
    drift = 1.0 - np.sum(patches * patches[0:1], axis=2)         # [n, P]
    patch_max_drift = drift.max(axis=0)
    return {
        "patch_jump_p90": float(np.percentile(patch_max_jump, 90)),
        "patch_jump_p99": float(np.percentile(patch_max_jump, 99)),
        "patch_drift_p90": float(np.percentile(patch_max_drift, 90)),
    }


def _masked_cls_metrics(patches) -> dict:
    """DINO-PCA foreground mask -> CLS-like instability over character patches only.
    First PCA component of all patch tokens separates fg/bg; sign-align so central
    patches are foreground; per-frame masked feature = mean of fg patches."""
    import numpy as np
    n, P, d = patches.shape
    if n < 2:
        return {"masked_instability": 0.0, "masked_worst_jump": 0.0,
                "masked_diameter": 0.0, "fg_frac": 0.0}
    side = int(round(P ** 0.5))
    flat = patches.reshape(n * P, d)
    mu = flat.mean(axis=0)
    _, _, vt = np.linalg.svd(flat - mu, full_matrices=False)
    comp = vt[0]
    proj = (patches - mu) @ comp                        # [n, P]
    # sign-align: central patches should be foreground (proj > 0)
    if side * side == P:
        grid = proj.reshape(n, side, side)
        c = side // 4
        center = grid[:, c:side - c, c:side - c].mean()
        edge = (grid[:, 0, :].mean() + grid[:, -1, :].mean()) / 2.0
        if center < edge:
            proj = -proj
    masked = np.zeros((n, d), dtype=np.float64)
    fg_counts = []
    for t in range(n):
        fg = proj[t] > 0.0
        if fg.sum() < 5:
            fg = np.ones(P, dtype=bool)
        fg_counts.append(fg.mean())
        v = patches[t][fg].mean(axis=0)
        masked[t] = v / (np.linalg.norm(v) + 1e-8)
    consec = np.sum(masked[:-1] * masked[1:], axis=1)
    gram = masked @ masked.T
    return {
        "masked_instability": float(1.0 - consec.mean()),
        "masked_worst_jump": float(1.0 - consec.min()),
        "masked_diameter": float((1.0 - gram).max()),
        "fg_frac": float(np.mean(fg_counts)),
    }


def score_clips(clips_dir, *, model_id="facebook/dinov2-small", device="cuda",
                batch=8, crop=518, only=None) -> dict:
    subdirs = sorted(d for d in os.listdir(clips_dir)
                     if os.path.isdir(os.path.join(clips_dir, d))
                     and (only is None or d in only))
    proc, model = _load_dino(model_id, device, crop)
    out = []
    for d in subdirs:
        paths = _frame_paths(os.path.join(clips_dir, d))
        if not paths:
            continue
        cls, pat = _features(paths, proc, model, device, batch)
        rec = {"clip": d, "n": int(len(paths))}
        rec.update(_cls_metrics(cls))
        rec.update(_patch_metrics(pat))
        rec.update(_masked_cls_metrics(pat))
        out.append(rec)
        print(f"  {d}: jump={rec['worst_jump']:.3f} diam={rec['diameter']:.3f} "
              f"patch90={rec['patch_jump_p90']:.3f} "
              f"mask_jump={rec['masked_worst_jump']:.3f} fg={rec['fg_frac']:.2f}",
              flush=True)
    return {"model": model_id, "crop": crop, "clips_dir": clips_dir, "clips": out}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--clips", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--model", default="facebook/dinov2-small")
    ap.add_argument("--device", default="cuda")
    ap.add_argument("--batch", type=int, default=8)
    ap.add_argument("--crop", type=int, default=518)
    args = ap.parse_args()
    res = score_clips(args.clips, model_id=args.model, device=args.device,
                      batch=args.batch, crop=args.crop)
    with open(args.out, "w") as f:
        json.dump(res, f, indent=1)
    print(f"wrote {args.out} ({len(res['clips'])} clips)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
