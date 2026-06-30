# inbetween_copilot/signals/motion.py
"""Reference-free MOTION primitives (re-export of benchmark.lib.signals.motion_primitives).

These deterministic numpy/PIL signals (gap_score, lin_resid, jerk, anti_ghost_ok,
load_frames) are shared infrastructure used across the whole benchmark research
tree, so they physically LIVE in benchmark/. The pipeline imports them through
this thin re-export layer to keep a single clean internal API (`inbetween_copilot.
signals.*`) without duplicating — or risking drift from — the upstream definitions.
"""
from __future__ import annotations

from benchmark.lib.signals.motion_primitives import (  # noqa: F401
    GHOST_LO,
    LOW_MOTION,
    anti_ghost_ok,
    gap_score,
    jerk,
    lin_resid,
    load_frames,
)

__all__ = [
    "gap_score",
    "lin_resid",
    "jerk",
    "anti_ghost_ok",
    "load_frames",
    "GHOST_LO",
    "LOW_MOTION",
]
