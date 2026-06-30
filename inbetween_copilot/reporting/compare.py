"""Build a side-by-side ORIGINAL-vs-RECONSTRUCTION comparison sequence.

The released-video-as-test setup decimates a real cut stride-2: the even frames
are the artist's kept keys (``src``) and the odd frames are the hidden ground
truth (``gt``) the co-pilot must reconstruct. Two full-rate sequences then exist:

  ORIGINAL = interleave(src, gt)        -> the true cut (gt is the real in-between)
  RECON    = interleave(src, rife_mids) -> the co-pilot output (RIFE guesses it)

Played frame-synced, even positions are the shared key (identical on both sides)
and odd positions show the real GT versus the RIFE guess — the most honest visual
QA of interpolation quality. These builders are pure (numpy only); the RIFE pass
and the mp4 encode live in the box script that calls them.
"""
from __future__ import annotations

from typing import List

import numpy as np


def interleave(a: List[np.ndarray], b: List[np.ndarray]) -> List[np.ndarray]:
    """Weave two frame lists: a[0], b[0], a[1], b[1], ...  When ``b`` is one
    shorter than ``a`` (RIFE has n-1 mids for n keys) the result ends on a[-1]."""
    out: List[np.ndarray] = []
    for i, frame in enumerate(a):
        out.append(frame)
        if i < len(b):
            out.append(b[i])
    return out


def side_by_side(left: np.ndarray, right: np.ndarray, divider_px: int = 4,
                 divider_color: tuple = (255, 255, 255)) -> np.ndarray:
    """Horizontally stack two equal-height frames with a divider strip between."""
    if left.shape[0] != right.shape[0]:
        raise ValueError(f"height mismatch: left {left.shape[0]} != right {right.shape[0]}")
    h = left.shape[0]
    divider = np.empty((h, divider_px, 3), np.uint8)
    divider[:] = divider_color
    return np.concatenate([left, divider, right], axis=1)


def build_split_sequences(src: List[np.ndarray], gt: List[np.ndarray],
                          mids: List[np.ndarray]) -> tuple[List[np.ndarray], List[np.ndarray]]:
    """Return the two frame-synced full-rate cuts (ORIGINAL, RECON), equal length.

    ``src`` = n kept keys, ``gt`` = hidden GT (>= n-1), ``mids`` = RIFE mids (n-1).
    Both are truncated to the recon length 2n-1 so they stay aligned (the trailing GT
    frame after the final key has no recon counterpart). The client before/after wipe
    plays these two stacked and clips between them over identical pixels."""
    n = len(src)
    if len(mids) != n - 1:
        raise ValueError(f"expected {n - 1} mids for {n} keys, got {len(mids)}")
    if len(gt) < n - 1:
        raise ValueError(f"need >= {n - 1} GT frames, got {len(gt)}")
    original = interleave(src, gt)
    recon = interleave(src, mids)
    length = len(recon)                 # 2n-1
    return original[:length], recon[:length]


def build_comparison_frames(src: List[np.ndarray], gt: List[np.ndarray],
                            mids: List[np.ndarray], divider_px: int = 4) -> List[np.ndarray]:
    """Return frame-synced side-by-side frames (left = ORIGINAL, right = RECON).

    Thin wrapper over :func:`build_split_sequences` that stacks the two cuts with a divider."""
    original, recon = build_split_sequences(src, gt, mids)
    return [side_by_side(l, r, divider_px) for l, r in zip(original, recon)]
