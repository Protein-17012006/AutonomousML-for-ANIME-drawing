"""The validated detector prompt literals — DEPENDENCY-FREE on purpose.

_MOTION_PROMPT used to live in motion_arms.py, whose top-level imports
vision_common — so re-exporting it (inbetween_copilot/signals/prompt.py)
transitively loaded the whole VLM client into the "pure" pipeline on ANY
signals import (audit 2026-07-02 finding #4). Prompt text has no business
depending on an HTTP client; it lives here so both the benchmark arms and the
pipeline facade can import it without pulling vision_common.
"""
from __future__ import annotations

_MOTION_PROMPT = """\
These are consecutive frames of one short animation clip, in order. Judge ONLY
the motion across them.

Some clips are clean: smooth, coherent anime motion. Some contain a motion error
from a generative interpolator — a limb that warps or melts, the character's
identity or colors drifting between frames, a motion arc that breaks or reverses
illogically, flicker/popping, or an impossible morph.

Intentional anime stylization (smears, speed lines, squash-and-stretch) is NOT an
error. Only flag a genuine breakdown in motion coherence.

Return JSON: {"has_motion_error": true or false, "explanation": "<one sentence>"}"""
