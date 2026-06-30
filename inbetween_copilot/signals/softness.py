# inbetween_copilot/signals/softness.py
"""Reference-free interp-SOFTNESS ghost signal (re-export of
benchmark.smallgap.signals.softness_signal).

interp_softness(frames) -> {soft_mean, soft_worst}: how much softer the
interpolated (odd) frames are than the real (even) source frames — the
free-recall ghost signal the QA softness/sharpness channels consume.
"""
from __future__ import annotations

from benchmark.smallgap.signals.softness_signal import interp_softness  # noqa: F401

__all__ = ["interp_softness"]
