"""Single source of truth for key/mid frame indices of one eval clip.

A clip trimmed to n_used = n_gaps*tsf + 1 frames has keys every tsf frames
(both endpoints inclusive); everything else is a hidden mid the engines must
reconstruct. Mirrors benchmark/widegap/prep/decimate_wide.py but flat
(index lists, not per-pair), because engines here fill the WHOLE span.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class SpanPlan:
    n_used: int
    key_idx: list[int]
    mid_idx: list[int]


def plan_span(n_frames: int, tsf: int) -> SpanPlan:
    if tsf < 2:
        raise ValueError(f"tsf must be >= 2, got {tsf}")
    n_gaps = (n_frames - 1) // tsf
    if n_gaps < 1:
        raise ValueError(f"need >= tsf+1 frames, got {n_frames} (tsf {tsf})")
    n_used = n_gaps * tsf + 1
    key_idx = list(range(0, n_used, tsf))
    mid_idx = [i for i in range(n_used) if i % tsf != 0]
    return SpanPlan(n_used=n_used, key_idx=key_idx, mid_idx=mid_idx)
