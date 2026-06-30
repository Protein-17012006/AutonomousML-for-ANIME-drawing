# benchmark/smallgap/run_smallgap.py
"""Re-validate the production motion detector on the frozen suite_smallgap and
write the baseline.

Runs the SAME production config as the other frozen suites: run_clip_arm
(`_MOTION_PROMPT`) against the served `motion_lora16_rife` at max_pixels=320
(launch with .scratch/serve_artifact.sh + an SSH tunnel; this process talks to
it via VISION_BASE_URL_CHECK). Slices precision/recall by regime x generator,
correlates the detector flag with PSNR, and — given the window plan — reports
the deterministic gap-gate AUC (snap vs interpolable).

  VISION_BASE_URL_CHECK=http://localhost:8000/v1 VISION_MODEL_CHECK=qwen3vl-anime \
      python -m benchmark.smallgap.run_smallgap --suite benchmark/suites/suite_smallgap \
      --windows .scratch/smallgap/selected_windows.json
"""
from __future__ import annotations

import argparse
import json
import os

import numpy as np

from benchmark.lib.detector.motion_arms import run_clip_arm
from benchmark.lib.manifest.motion_manifest import load_motion_manifest
from benchmark.lib.scoring.motion_score import score_motion
from benchmark.smallgap.score.evaluate import slice_scores, gate_auc


def _gate(windows_path: str) -> dict | None:
    """Deterministic interpolable-gate AUC: max source-step motion separates
    snap (not interpolable) from small+hold. Window-level (dedup of rife/blend)."""
    if not windows_path or not os.path.exists(windows_path):
        return None
    sel = json.load(open(windows_path))["selected"]
    seen, motions, is_snap = set(), [], []
    for w in sel:
        if w["wid"] in seen:
            continue
        seen.add(w["wid"])
        motions.append(float(w["max_step"]))
        is_snap.append(w["regime"] == "snap")
    return {"auc": gate_auc(motions, is_snap), "n_windows": len(motions),
            "n_snap": int(sum(is_snap))}


def run(suite_dir: str, windows_path: str | None) -> dict:
    manifest = load_motion_manifest(os.path.join(suite_dir, "manifest.json"))
    if not manifest.frozen:
        raise SystemExit("[ABORT] suite_smallgap manifest is not frozen.")
    verdicts = run_clip_arm(suite_dir, manifest)
    overall = score_motion(verdicts, manifest)

    flags, psnrs = [], []
    for c in manifest.clips:
        f = verdicts.get(c["id"], {}).get("has_motion_error")
        if isinstance(f, bool) and isinstance(c.get("psnr"), (int, float)):
            flags.append(int(f)); psnrs.append(float(c["psnr"]))
    corr = (float(np.corrcoef(flags, psnrs)[0, 1])
            if len(set(flags)) > 1 and len(flags) > 2 else None)

    obj = {}
    for r in ("hold", "small", "snap"):
        ps = [c["psnr"] for c in manifest.clips
              if c["regime"] == r and isinstance(c.get("psnr"), (int, float))]
        ss = [c["ssim"] for c in manifest.clips
              if c["regime"] == r and isinstance(c.get("ssim"), (int, float))]
        obj[r] = {"psnr_mean": round(float(np.mean(ps)), 2) if ps else None,
                  "ssim_mean": round(float(np.mean(ss)), 3) if ss else None,
                  "n": len(ps)}

    return {"suite": suite_dir, "overall": overall,
            "by_regime": slice_scores(verdicts, manifest, "regime"),
            "by_gen": slice_scores(verdicts, manifest, "gen"),
            "by_regime_gen": slice_scores(verdicts, manifest, "regime+gen"),
            "objective_by_regime": obj, "corr_flag_psnr": corr,
            "gate": _gate(windows_path), "verdicts_by_clip": verdicts}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--suite", default="benchmark/suites/suite_smallgap")
    ap.add_argument("--windows", default="")
    args = ap.parse_args()
    report = run(args.suite, args.windows)
    show = {k: v for k, v in report.items() if k != "verdicts_by_clip"}
    print(json.dumps(show, indent=2))
    out = os.path.join(args.suite, "signal_baseline.json")
    with open(out, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2)
    print(f"\nwrote {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
