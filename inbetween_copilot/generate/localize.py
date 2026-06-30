"""Where is the flagged in-between wrong? (the correction loop's localizer).

Reference-free `localize_softness` is the deployable channel: it picks the
tiles where the interpolated (odd) frames are softer than the real (even)
source frames -- the spatial form of `interp_softness`. `localize_gt` is a
GROUND-TRUTH ceiling for measurement only (needs GT, never deployed). A
`Region` with an empty mask means "whole frame" (the localizer could not pin
a tile). Pure numpy + the validated `frame_sharpness` primitive, GPU-free.

`localize_held_soft` and `hold_fixable_fraction` add a fidelity-aware,
motion-gated variant: only tiles that are BOTH soft AND motion-held qualify.
Motivation: region-refill (hold-copy into soft tiles) HARMS PSNR on
soft-but-MOVING tiles but HELPS strongly on soft-and-HELD tiles (+5 to +12
dB). The "held" gate is determined by `_tile_motion`, which measures max
gap_score over consecutive source (even-index) frames within the tile.
`hold_fixable_fraction` is the director's reference-free signal: of the soft
tiles, what fraction are also held (and therefore hold-fixable)?
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from inbetween_copilot.signals.sharpness import frame_sharpness
from inbetween_copilot.signals.objective import psnr
from inbetween_copilot.signals.motion import gap_score

_EPS = 1e-6


@dataclass(frozen=True)
class Region:
    grid: int
    mask: tuple          # tuple of (row, col) tiles; () = whole frame


def _tile_bounds(h: int, w: int, grid: int, r: int, c: int):
    return (r * h // grid, (r + 1) * h // grid, c * w // grid, (c + 1) * w // grid)


def localize_softness(frames, *, grid: int = 4, top_k: int = 2) -> Region:
    arrs = [np.asarray(f) for f in frames]
    src = arrs[0::2]
    interp = arrs[1::2]
    if not src or not interp:
        return Region(grid=grid, mask=())
    h, w = arrs[0].shape[:2]
    scored = []
    for r in range(grid):
        for c in range(grid):
            y0, y1, x0, x1 = _tile_bounds(h, w, grid, r, c)
            s = float(np.mean([frame_sharpness(a[y0:y1, x0:x1]) for a in src]))
            m = float(np.mean([frame_sharpness(a[y0:y1, x0:x1]) for a in interp]))
            soft = 1.0 - (m / s if s > _EPS else 1.0)
            scored.append(((r, c), soft))
    scored.sort(key=lambda t: t[1], reverse=True)
    mask = tuple(rc for rc, soft in scored[:top_k] if soft > _EPS)
    return Region(grid=grid, mask=mask)


def localize_gt(recon_frame, gt_frame, *, grid: int = 4, top_k: int = 2) -> Region:
    a = np.asarray(recon_frame)
    g = np.asarray(gt_frame)
    h, w = a.shape[:2]
    scored = []
    for r in range(grid):
        for c in range(grid):
            y0, y1, x0, x1 = _tile_bounds(h, w, grid, r, c)
            scored.append(((r, c), psnr(a[y0:y1, x0:x1], g[y0:y1, x0:x1])))
    scored.sort(key=lambda t: t[1])          # ascending: worst (lowest) psnr first
    return Region(grid=grid, mask=tuple(rc for rc, _ in scored[:top_k]))


def _tile_motion(frames, grid: int, r: int, c: int) -> float:
    """Max gap_score over consecutive SOURCE (even-index) frames within tile (r, c).

    SOURCE frames are at even indices in the window layout [s0, m0, s1, m1, ...].
    Returns 0.0 if fewer than 2 source frames are present.
    """
    arrs = [np.asarray(f) for f in frames]
    src = arrs[0::2]
    if len(src) < 2:
        return 0.0
    h, w = arrs[0].shape[:2]
    y0, y1, x0, x1 = _tile_bounds(h, w, grid, r, c)
    tiles = [s[y0:y1, x0:x1] for s in src]
    return max(gap_score(tiles[i], tiles[i + 1]) for i in range(len(tiles) - 1))


def localize_held_soft(
    frames,
    *,
    grid: int = 4,
    tau_motion: float = 0.006,
    soft_thr: float = 0.10,
) -> Region:
    """Fidelity-aware, motion-gated localizer: returns tiles that are BOTH soft AND held.

    Per-tile softness = 1 - mean(interp sharpness) / mean(source sharpness), mirroring
    `localize_softness`. A tile qualifies if softness > soft_thr AND tile_motion < tau_motion.

    Calibration note: tau_motion=0.006 is calibrated from a 2026-06-22 tile-motion probe
    (held tiles Q1 motion<0.006 gave +5.15 dB hold-vs-interp; moderate motion harmed).
    UNCALIBRATED on content outside that probe. Reference-free (no GT) -> deployable.

    Returns Region(grid=grid, mask=tuple of (row,col) sorted by softness descending).
    Empty mask means no qualifying tile (either flat clip, no soft tiles, or all soft tiles
    are moving).
    """
    arrs = [np.asarray(f) for f in frames]
    src = arrs[0::2]
    interp = arrs[1::2]
    if not src or not interp:
        return Region(grid=grid, mask=())
    h, w = arrs[0].shape[:2]

    qualified = []
    for r in range(grid):
        for c in range(grid):
            y0, y1, x0, x1 = _tile_bounds(h, w, grid, r, c)
            s_sharp = float(np.mean([frame_sharpness(a[y0:y1, x0:x1]) for a in src]))
            m_sharp = float(np.mean([frame_sharpness(a[y0:y1, x0:x1]) for a in interp]))
            softness = 1.0 - (m_sharp / s_sharp if s_sharp > _EPS else 1.0)
            if softness > soft_thr and _tile_motion(frames, grid, r, c) < tau_motion:
                qualified.append(((r, c), softness))

    qualified.sort(key=lambda t: t[1], reverse=True)
    return Region(grid=grid, mask=tuple(rc for rc, _ in qualified))


def hold_fixable_fraction(
    frames,
    *,
    grid: int = 4,
    tau_motion: float = 0.006,
    soft_thr: float = 0.10,
) -> float:
    """Of soft tiles, the fraction that are also held (motion < tau_motion).

    This is the director's reference-free "is this region hold-fixable?" reward.
    Returns 0.0 if there are no soft tiles.

    Calibration note: tau_motion=0.006 is calibrated from a 2026-06-22 tile-motion
    probe (held tiles Q1 motion<0.006 gave +5.15 dB hold-vs-interp). UNCALIBRATED
    on other content. Reference-free (no GT) -> deployable.
    """
    arrs = [np.asarray(f) for f in frames]
    src = arrs[0::2]
    interp = arrs[1::2]
    if not src or not interp:
        return 0.0
    h, w = arrs[0].shape[:2]

    n_soft = 0
    n_held_and_soft = 0
    for r in range(grid):
        for c in range(grid):
            y0, y1, x0, x1 = _tile_bounds(h, w, grid, r, c)
            s_sharp = float(np.mean([frame_sharpness(a[y0:y1, x0:x1]) for a in src]))
            m_sharp = float(np.mean([frame_sharpness(a[y0:y1, x0:x1]) for a in interp]))
            softness = 1.0 - (m_sharp / s_sharp if s_sharp > _EPS else 1.0)
            if softness > soft_thr:
                n_soft += 1
                if _tile_motion(frames, grid, r, c) < tau_motion:
                    n_held_and_soft += 1

    return float(n_held_and_soft / n_soft) if n_soft > 0 else 0.0
