# benchmark/smallgap/decimate.py
"""Pure 2x decimation index split for a fixed-length native-frame window.

A window of `window_len` consecutive native frames is split into EVEN source
positions (the half-fps input the interpolator sees) and ODD ground-truth
positions (hidden, reconstructed and scored). Each interpolation Step bridges
two consecutive source frames (a, b) to predict the GT frame between them.
The detector is fed the first 16 positions (8 real + 8 interpolated).
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Step:
    a: int
    gt: int
    b: int


@dataclass
class WindowSplit:
    window_len: int
    source: list[int]
    gt: list[int]
    steps: list[Step]
    stored: list[int]


def decimate(window_len: int = 17) -> WindowSplit:
    if window_len < 3 or window_len % 2 == 0:
        raise ValueError(f"window_len must be odd and >= 3, got {window_len}")
    source = list(range(0, window_len, 2))
    gt = list(range(1, window_len, 2))
    steps = [Step(a=g - 1, gt=g, b=g + 1) for g in gt]
    # The detector sees the first 16 interleaved positions (8 real + 8 GT).
    # Derive from source/gt rather than a hardcoded range(16) so a non-17
    # window never yields out-of-range indices.
    stored = sorted(source[:8] + gt[:8])
    return WindowSplit(window_len=window_len, source=source, gt=gt,
                       steps=steps, stored=stored)
