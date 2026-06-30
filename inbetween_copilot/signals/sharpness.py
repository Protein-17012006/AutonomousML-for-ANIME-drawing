# inbetween_copilot/signals/sharpness.py
"""SHARPNESS / spatial-quality primitives (re-export of benchmark.lib.signals.spatial_quality).

frame_sharpness (Laplacian variance) is the shared low-level primitive the
softness signal, the CSQ sharpness channel, and the localizer all build on;
clip_score / SPATIAL_THRESH / LAP_REF are the absolute-sharpness QA scoring.
Shared infra — lives in benchmark/, surfaced here as the pipeline's clean API.
"""
from __future__ import annotations

from benchmark.lib.signals.spatial_quality import (  # noqa: F401
    LAP_REF,
    SPATIAL_THRESH,
    blur_deficit,
    clip_score,
    frame_sharpness,
    lap_var,
    worst_frames,
)

__all__ = [
    "frame_sharpness",
    "clip_score",
    "SPATIAL_THRESH",
    "LAP_REF",
    "lap_var",
    "blur_deficit",
    "worst_frames",
]
