# inbetween_copilot/signals/prompt.py
"""The validated detector PROMPT (re-export of benchmark.lib.detector.prompts._MOTION_PROMPT).

`_MOTION_PROMPT` is the exact, validated Qwen3-VL motion-error detector prompt the
QA perception agent conditions on. Imported from the dependency-free prompts module —
NOT from motion_arms, whose top-level pulls the vision_common VLM client and used to
leak it into the pure package on any signals import (fixed in the 2026-07-02 audit).
"""
from __future__ import annotations

from benchmark.lib.detector.prompts import _MOTION_PROMPT  # noqa: F401

__all__ = ["_MOTION_PROMPT"]
