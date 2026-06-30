"""Keyframe-duplicate detector — ADR-0012 §1 (split discipline / leak guard).

Generated clips that share a SOURCE KEYFRAME are near-duplicates: our R1/R2 harvest re-rendered the
same 23 keyframes with different prompts/seeds, so two clips can be twins despite different ids. If
a random train/val/test split separates them, the metric is fake-pretty. Source-keyframe provenance
was NOT persisted (a gap this very tool exposes), so we recover it perceptually: an image-to-video
clip's frame_00 ≈ its input keyframe, so near-identical frame_00 ⇒ shared keyframe.

Outputs duplicate CLUSTERS that must be kept together in one split (and a suggested split-group id
per clip). PIL + numpy only, GPU-free.

    python -m benchmark.lib.signals.keyframe_dedup --clips <dir-of-clip-subdirs> [--thresh 0.93] [--out dup.json]
"""
from __future__ import annotations

import argparse
import json
import os

import numpy as np
from PIL import Image

_FRAME_EXTS = (".png", ".jpg", ".jpeg", ".webp")


def _first_frame(clip_dir: str) -> str | None:
    fs = [n for n in sorted(os.listdir(clip_dir)) if n.lower().endswith(_FRAME_EXTS)]
    return os.path.join(clip_dir, fs[0]) if fs else None


def _descriptor(path: str) -> np.ndarray:
    """Low-freq perceptual descriptor of a frame: 32x32 grayscale (structure) + 8x8 RGB (colour),
    each mean-subtracted and L2-normalised, concatenated. Robust to small render differences,
    discriminative across genuinely different keyframes."""
    img = Image.open(path).convert("RGB")
    g = np.asarray(img.convert("L").resize((32, 32), Image.LANCZOS), np.float32).ravel()
    c = np.asarray(img.resize((8, 8), Image.LANCZOS), np.float32).ravel()
    g -= g.mean(); c -= c.mean()
    g /= (np.linalg.norm(g) + 1e-8); c /= (np.linalg.norm(c) + 1e-8)
    return np.concatenate([g, c])


class _UF:
    def __init__(self, n): self.p = list(range(n))
    def find(self, x):
        while self.p[x] != x:
            self.p[x] = self.p[self.p[x]]; x = self.p[x]
        return x
    def union(self, a, b): self.p[self.find(a)] = self.find(b)


def find_duplicates(clips_dir: str, thresh: float = 0.93):
    subs = sorted(d for d in os.listdir(clips_dir)
                  if os.path.isdir(os.path.join(clips_dir, d)))
    ids, descs = [], []
    for d in subs:
        ff = _first_frame(os.path.join(clips_dir, d))
        if ff:
            ids.append(d); descs.append(_descriptor(ff))
    if not ids:
        return [], {}, np.zeros((0, 0))
    X = np.stack(descs)                      # [n, D], rows L2-normalised per block (2-block)
    # cosine via dot of half-vectors averaged (both blocks unit-norm -> dot in [-1,1] each)
    half = X.shape[1] - 64
    S = 0.5 * (X[:, :half] @ X[:, :half].T) + 0.5 * (X[:, half:] @ X[:, half:].T)
    uf = _UF(len(ids))
    pairs = []
    for i in range(len(ids)):
        for j in range(i + 1, len(ids)):
            if S[i, j] >= thresh:
                uf.union(i, j); pairs.append((ids[i], ids[j], float(S[i, j])))
    groups: dict[int, list[str]] = {}
    for i, cid in enumerate(ids):
        groups.setdefault(uf.find(i), []).append(cid)
    clusters = [sorted(v) for v in groups.values() if len(v) > 1]
    split_group = {cid: f"kf{uf.find(i):03d}" for i, cid in enumerate(ids)}
    return sorted(clusters), split_group, S, ids, pairs


def run(clips_dir: str, thresh: float, out: str | None) -> int:
    clusters, split_group, S, ids, pairs = find_duplicates(clips_dir, thresh)
    print(f"clips: {len(ids)}   threshold: {thresh}")
    print(f"duplicate clusters (share a keyframe -> keep in ONE split): {len(clusters)}")
    for c in clusters:
        print(f"  {c}")
    dup_clips = sum(len(c) for c in clusters)
    print(f"\n{dup_clips}/{len(ids)} clips are in a duplicate cluster; "
          f"{len(set(split_group.values()))} independent split-groups total.")
    if pairs:
        top = sorted(pairs, key=lambda p: -p[2])[:8]
        print("top duplicate pairs (sim):")
        for a, b, s in top:
            print(f"  {a} ~ {b}: {s:.3f}")
    if out:
        json.dump({"clips_dir": clips_dir, "threshold": thresh,
                   "clusters": clusters, "split_group": split_group},
                  open(out, "w"), indent=1)
        print(f"wrote {out}")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--clips", required=True)
    ap.add_argument("--thresh", type=float, default=0.93)
    ap.add_argument("--out", default=None)
    args = ap.parse_args()
    return run(args.clips, args.thresh, args.out)


if __name__ == "__main__":
    raise SystemExit(main())
