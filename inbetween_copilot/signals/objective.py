# inbetween_copilot/signals/objective.py
"""OBJECTIVE (ground-truth) metrics (re-export of benchmark.smallgap.score.objective).

psnr is a GT-only ceiling: used by the localizer's `localize_gt` measurement
path and by offline GT-labelling — never on a deployed reference-free path.
"""
from __future__ import annotations

from benchmark.smallgap.score.objective import (  # noqa: F401
    PSNR_MAX,
    clip_objective,
    psnr,
    ssim,
)

__all__ = ["psnr", "ssim", "PSNR_MAX", "clip_objective"]
