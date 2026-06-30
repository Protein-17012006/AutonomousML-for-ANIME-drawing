"""Reference-free interp-softness ghost signal for small-gap 2x clips.

A small-gap RIFE on-2s/smear ghost tends to BLUR the interpolated in-between
(smear / hold-morph), so the interp frames are softer than their real source
neighbours. This is detectable with NO ground truth and NO VLM -- only the clip.

Clip layout = [s0, m0, s1, m1, ..., s7, m7]: even index = real source frame,
odd index = the RIFE-interpolated middle. Sharpness = Laplacian variance
(`spatial_quality.frame_sharpness`).

Validated on suite_on2s_v2 (2026-06-20): soft_mean AUC 0.827; fused with the
detector (`v2 OR soft_mean>0.15`) recall 0.417 -> 0.708 at precision ~0.90.
Sibling of `benchmark/spatial_quality.py` (the integrity-axis sharpness signal).
"""
from __future__ import annotations

import numpy as np

from benchmark.lib.signals.spatial_quality import frame_sharpness

_EPS = 1e-6


def interp_softness(frames, *, size: int = 256) -> dict:
    """How much softer the interp (odd) frames are than the source (even) frames.

    `frames` is a 16-frame 2x clip (paths or arrays). Returns ``soft_mean`` =
    ``1 - mean(interp_sharpness) / mean(source_sharpness)`` (a uniformly soft
    clip) and ``soft_worst`` = ``1 - min(interp_sharpness) / mean(source)`` (a
    single transiently-soft interp frame among sharp ones). Both higher = softer
    = more ghost, clamped to [0, 1]. A flat clip (no source sharpness to judge
    against) yields 0 (no signal).
    """
    source = [frame_sharpness(frames[i], size=size) for i in range(0, len(frames), 2)]
    interp = [frame_sharpness(frames[i], size=size) for i in range(1, len(frames), 2)]
    ref = float(np.mean(source))
    if ref < _EPS:
        return {"soft_mean": 0.0, "soft_worst": 0.0}
    soft_mean = 1.0 - float(np.mean(interp)) / ref
    soft_worst = 1.0 - float(np.min(interp)) / ref
    return {"soft_mean": float(np.clip(soft_mean, 0.0, 1.0)),
            "soft_worst": float(np.clip(soft_worst, 0.0, 1.0))}
