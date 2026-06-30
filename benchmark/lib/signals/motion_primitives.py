"""Deterministic signal functions for the repair cascade.

Anti-ghost discriminator and helpers used by select.py to filter degenerate
linear-crossfade candidates before ranking.

All frame inputs are lists of HxWx3 uint8 numpy arrays (RGB).
No torch, no cv2, no network, no model calls.
"""
from __future__ import annotations

import numpy as np
from PIL import Image

# Module-level defaults (measured: real-generator lin_resid min ~0.033;
# crossfade ghost ~0.002).
GHOST_LO: float = 0.03
LOW_MOTION: float = 0.06


def load_frames(paths: list[str]) -> list[np.ndarray]:
    """Load RGB frames from disk as uint8 numpy arrays."""
    return [np.asarray(Image.open(p).convert("RGB"), dtype=np.uint8)
            for p in paths]


def lin_resid(frames: list[np.ndarray]) -> float:
    """Mean deviation of interior frames from the linear A→B crossfade.

    For each interior frame i (1 … n-2), compute:
        |f_i - ((1 - t)*A + t*B)| / 255   where t = i / (n-1)
    and return the mean over all interior frames.

    Returns 0.0 if fewer than 3 frames are supplied.
    ~0.002 for a pure crossfade ghost; ~0.05-0.17 for real interpolation.
    """
    n = len(frames)
    if n < 3:
        return 0.0
    A = frames[0].astype(np.float32)
    B = frames[-1].astype(np.float32)
    devs = [
        float(np.abs(frames[i].astype(np.float32)
                     - ((1 - i / (n - 1)) * A + (i / (n - 1)) * B)).mean() / 255.0)
        for i in range(1, n - 1)
    ]
    return float(np.mean(devs))


def gap_score(a: np.ndarray, b: np.ndarray) -> float:
    """Mean absolute endpoint dissimilarity, normalised to [0, 1].

    a, b are HxWx3 uint8 arrays.
    """
    return float(np.abs(a.astype(np.float32) - b.astype(np.float32)).mean() / 255.0)


def jerk(frames: list[np.ndarray]) -> float:
    """Mean second-difference (acceleration proxy) computed on grayscale.

    For each interior frame i (1 … n-2):
        |f_{i+1} - 2*f_i + f_{i-1}|  (grayscale, float)
    Returns the mean over all such frames, or 0.0 if fewer than 3 frames.
    """
    n = len(frames)
    if n < 3:
        return 0.0

    def _gray(f: np.ndarray) -> np.ndarray:
        f32 = f.astype(np.float32)
        return 0.299 * f32[..., 0] + 0.587 * f32[..., 1] + 0.114 * f32[..., 2]

    grays = [_gray(f) for f in frames]
    devs = [
        float(np.abs(grays[i + 1] - 2 * grays[i] + grays[i - 1]).mean())
        for i in range(1, n - 1)
    ]
    return float(np.mean(devs))


def anti_ghost_ok(
    frames: list[np.ndarray],
    *,
    ghost_lo: float = GHOST_LO,
    low_motion: float = LOW_MOTION,
) -> bool:
    """Return True iff the clip is NOT a degenerate linear-crossfade ghost.

    Logic:
      gap = gap_score(frames[0], frames[-1])
      if gap <= low_motion: return True   # near-static: linear mean is legit
      return lin_resid(frames) > ghost_lo  # reject crossfade ghosts
    """
    gap = gap_score(frames[0], frames[-1])
    if gap <= low_motion:
        return True
    return lin_resid(frames) > ghost_lo
