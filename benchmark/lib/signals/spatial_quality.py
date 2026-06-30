"""Spatial no-reference quality signal (per-frame sharpness degradation).

Orthogonal companion to identity_signal.py (DINO TEMPORAL instability). The
temporal signal is blind to a SPATIALLY-static artifact: id002 is interlace-
ghosting -- doubled/softened within each frame but stable ACROSS frames, so DINO
temporal cosine stays high (instability 0.023, missed). This channel reads
WITHIN-frame quality instead.

DATA FINDING (2026-06-17, real suite_integrity clips): id002's ghosting does NOT
show as a row-alternating interlace comb at this resolution (comb metrics ~0
everywhere). It shows as SOFTNESS -- id002 has the lowest Laplacian variance of
the suite. So the orthogonal feature is sharpness degradation, NOT a bespoke
ghost-autocorrelation (that primitive was unsupported by the data -> dropped).
Two terms, because a defect is soft in two distinct ways:

  abs_softness  -- a uniformly soft clip (id002: ghosting softens every frame).
                   exp(-p10_lap_var / lap_ref): low sharpness -> high score.
  rel_drop      -- a transiently soft clip (one melt/smear frame among sharp
                   ones): (clip_median - worst_frame) / clip_median.

score = max(abs_softness, rel_drop). HONEST LIMIT: a no-reference sharpness
metric cannot tell a DEFECT-soft frame (id002) from an INTENTionally-soft clean
scene (id035, the softest clip, labelled clean) -- the same magnitude-can't-
encode-intent wall as the DINO signal's 0.74 precision ceiling. This is an
ENSEMBLE lever measured under OR-union, not a standalone classifier. Pure
numpy/PIL, GPU-free. Verdict mirrors motion_signal.flicker_verdict.
"""
from __future__ import annotations

import numpy as np
from PIL import Image

from benchmark.lib.signals.motion_signal import _frame_paths   # reuse the sorted-frame walker

LAP_REF = 120.0                # sharpness normalization -- UNCALIBRATED default
SPATIAL_THRESH = 0.50          # tau2 -- UNCALIBRATED default; set by .scratch/eval_spatial_or.py


def lap_var(gray) -> float:
    """Variance of the 4-neighbour Laplacian (a no-reference focus measure):
    high = sharp, low = blurry/soft."""
    g = gray.astype(np.float64)
    lap = (4.0 * g[1:-1, 1:-1] - g[:-2, 1:-1] - g[2:, 1:-1]
           - g[1:-1, :-2] - g[1:-1, 2:])
    return float(lap.var())


def blur_deficit(gray, *, lap_ref: float = LAP_REF) -> float:
    """1 - sharpness, bounded (0,1]: sharp (high lap_var) -> ~0; soft -> ~1."""
    return float(np.exp(-lap_var(gray) / lap_ref))


def _to_gray(frame, *, size: int):
    if isinstance(frame, str):
        img = Image.open(frame).convert("L")
    else:
        arr = np.asarray(frame)
        img = Image.fromarray(arr.astype(np.uint8))
        if img.mode != "L":
            img = img.convert("L")
    if max(img.size) > size:                      # downscale long edge to `size`
        w, h = img.size
        s = size / max(w, h)
        img = img.resize((max(1, int(w * s)), max(1, int(h * s))))
    return np.asarray(img, dtype=np.float32)


def frame_sharpness(frame, *, size: int = 256) -> float:
    """Per-frame Laplacian variance (sharpness). `frame` = path or array."""
    return lap_var(_to_gray(frame, size=size))


def _sharpness_series(frames, *, size: int = 256) -> np.ndarray:
    return np.array([frame_sharpness(f, size=size) for f in frames],
                    dtype=np.float64)


def clip_score(frames, *, lap_ref: float = LAP_REF, drop_pct: int = 10,
               size: int = 256) -> float:
    """max(abs_softness, rel_drop) over the clip's per-frame sharpness series.

    abs_softness = exp(-p{drop_pct}(lap_var) / lap_ref)  -- uniform softness (id002).
    rel_drop     = (median - min) / median               -- a transiently soft frame.
    """
    lvs = _sharpness_series(frames, size=size)
    if lvs.size == 0:
        return 0.0
    abs_soft = float(np.exp(-np.percentile(lvs, drop_pct) / lap_ref))
    med = float(np.median(lvs))
    rel_drop = (med - float(lvs.min())) / (med + 1e-6) if med > 0 else 0.0
    return max(abs_soft, min(rel_drop, 1.0))


def worst_frames(frames, *, top: int = 3, size: int = 256) -> list[int]:
    """Indices of the blurriest (lowest-sharpness) frames, for inspection."""
    lvs = _sharpness_series(frames, size=size)
    if lvs.size == 0:
        return []
    order = sorted(range(len(lvs)), key=lambda i: lvs[i])   # ascending = blurriest first
    return sorted(order[:top])


def spatial_verdict(clip_dir: str, *, thresh: float = SPATIAL_THRESH, top: int = 3,
                    lap_ref: float = LAP_REF, drop_pct: int = 10,
                    size: int = 256) -> dict:
    paths = _frame_paths(clip_dir)
    if not paths:
        return {"has_spatial_defect": False, "score": 0.0, "worst_frames": []}
    score = clip_score(paths, lap_ref=lap_ref, drop_pct=drop_pct, size=size)
    wf = worst_frames(paths, top=top, size=size) if score > 0.0 else []
    return {"has_spatial_defect": score >= thresh, "score": score,
            "worst_frames": wf}
