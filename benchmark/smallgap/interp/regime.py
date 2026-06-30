# benchmark/smallgap/regime.py
"""Deterministic regime classification for decimated windows.

step_motions  — per-step gap_score between consecutive SOURCE frames.
scene_cut     — histogram-difference hard-cut detector.
classify      — hold / small / snap from the step motions + a cut flag.
"""
from __future__ import annotations

import numpy as np

from benchmark.lib.signals.motion_primitives import gap_score


def step_motions(source_frames: list[np.ndarray]) -> list[float]:
    return [gap_score(source_frames[i], source_frames[i + 1])
            for i in range(len(source_frames) - 1)]


def _gray_hist(f: np.ndarray, bins: int = 64) -> np.ndarray:
    g = (0.299 * f[..., 0] + 0.587 * f[..., 1] + 0.114 * f[..., 2])
    # range=(0, 256) gives 64 uniform 4-wide integer-aligned bins. (np.histogram
    # closes the last bin, so (0, 255) also counts value 255 — but its ~3.98-wide
    # bins are not integer-aligned; (0, 256) is the cleaner, exact choice.)
    h, _ = np.histogram(g, bins=bins, range=(0, 256))
    s = h.sum()
    return h.astype(np.float64) / s if s else h.astype(np.float64)


def scene_cut(a: np.ndarray, b: np.ndarray, thresh: float = 0.4) -> bool:
    return float(np.abs(_gray_hist(a) - _gray_hist(b)).sum()) > thresh


def classify(step_ms: list[float], *, tau_hold: float, tau_snap: float,
             has_cut: bool = False) -> str:
    if not step_ms:
        raise ValueError("classify: empty step_ms")
    if has_cut or any(m > tau_snap for m in step_ms):
        return "snap"
    if all(m < tau_hold for m in step_ms):
        return "hold"
    return "small"
