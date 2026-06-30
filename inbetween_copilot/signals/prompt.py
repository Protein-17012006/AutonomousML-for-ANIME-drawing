# inbetween_copilot/signals/prompt.py
"""The validated detector PROMPT (re-export of benchmark.lib.detector.motion_arms._MOTION_PROMPT).

`_MOTION_PROMPT` is the exact, validated Qwen3-VL motion-error detector prompt the
QA perception agent conditions on. Surfaced here so the pipeline does not reach
into benchmark.lib.detector.motion_arms (which also pulls the VLM client) by an ad-hoc path.
"""
from __future__ import annotations

from benchmark.lib.detector.motion_arms import _MOTION_PROMPT  # noqa: F401

__all__ = ["_MOTION_PROMPT"]
