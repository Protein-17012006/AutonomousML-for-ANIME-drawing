# inbetween_copilot/signals/regime.py
"""Deterministic REGIME classification (re-export of benchmark.smallgap.interp.regime).

classify(step_motions, tau_hold, tau_snap, has_cut) -> hold | small | snap, plus
scene_cut (histogram hard-cut) and step_motions. Drives the pipeline's per-pair
engine selection (route.choose_route).
"""
from __future__ import annotations

from benchmark.smallgap.interp.regime import (  # noqa: F401
    classify,
    scene_cut,
    step_motions,
)

__all__ = ["classify", "scene_cut", "step_motions"]
