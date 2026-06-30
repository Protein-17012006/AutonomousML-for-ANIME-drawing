"""Deterministic correction tools the director agent calls.

`hold_copy` is the anti-ghost fill (copy the nearest real key, never morph --
this is exactly why hold-aware beats RIFE on on-2s). `composite_region` blends
an alternate fill into ONLY the flagged tiles of each frame, keeping the good
regions of the original interpolation. Pure numpy; hard-edged tile composite
(seam feathering is a deferred refinement, see the plan's Notes). GPU-free.
"""
from __future__ import annotations

import numpy as np

from inbetween_copilot.generate.localize import Region, _tile_bounds


def hold_copy(a, b, n: int) -> list:
    a = np.asarray(a)
    b = np.asarray(b)
    half = (n + 1) // 2
    return [np.array(a) if i < half else np.array(b) for i in range(n)]


def composite_region(base_frames, fill_frames, region: Region) -> list:
    if len(base_frames) != len(fill_frames):
        raise ValueError("composite_region: base/fill length mismatch")
    if not region.mask:
        return [np.array(f) for f in fill_frames]
    out = []
    for base, fill in zip(base_frames, fill_frames):
        b = np.array(base)
        f = np.asarray(fill)
        h, w = b.shape[:2]
        for (r, c) in region.mask:
            y0, y1, x0, x1 = _tile_bounds(h, w, region.grid, r, c)
            b[y0:y1, x0:x1] = f[y0:y1, x0:x1]
        out.append(b)
    return out
