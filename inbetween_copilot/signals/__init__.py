# inbetween_copilot/signals/__init__.py
"""Reference-free signal layer: the pipeline's single clean API over the
deterministic primitives that physically live in benchmark/ (shared infra).

This is a re-export facade ONLY — no logic lives here. Moving these primitives
out of benchmark/ would break the wider research tree, so the pipeline depends
on them through this layer instead (DRY, no drift).
"""
from __future__ import annotations

from inbetween_copilot.signals.motion import (  # noqa: F401
    anti_ghost_ok,
    gap_score,
    jerk,
    lin_resid,
    load_frames,
)
from inbetween_copilot.signals.objective import psnr  # noqa: F401
from inbetween_copilot.signals.prompt import _MOTION_PROMPT  # noqa: F401
from inbetween_copilot.signals.regime import (  # noqa: F401
    classify,
    scene_cut,
    step_motions,
)
from inbetween_copilot.signals.sharpness import (  # noqa: F401
    SPATIAL_THRESH,
    clip_score,
    frame_sharpness,
)
from inbetween_copilot.signals.softness import interp_softness  # noqa: F401
