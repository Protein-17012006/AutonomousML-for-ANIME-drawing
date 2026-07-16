"""Product-aligned re-QA of reconstructed clips.

PSNR can reward blur and warping, so every engine output and the dense GT
control receive the same one-call, 16-frame treatment as the production
motion detector.  ``tier="check"`` selects the local Qwen detector on the
box through ``VISION_BASE_URL_CHECK`` / ``VISION_MODEL_CHECK``.
"""
from __future__ import annotations

import numpy as np

from benchmark.lib.detector.prompts import _MOTION_PROMPT


def subsample_paths(paths: list[str], k: int = 16) -> list[str]:
    """Choose at most ``k`` ordered paths with both clip endpoints included."""
    if k < 1:
        raise ValueError(f"k must be positive, got {k}")
    if len(paths) <= k:
        return list(paths)
    indices = sorted({int(round(i)) for i in np.linspace(0, len(paths) - 1, k)})
    return [paths[i] for i in indices]


def _as_bool(value) -> bool | None:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"yes", "true", "1"}:
            return True
        if normalized in {"no", "false", "0"}:
            return False
    return None


def flag_clip(frame_paths: list[str], vision_fn=None) -> dict:
    """Return a detector verdict without letting one failed call abort a run."""
    if vision_fn is None:
        from vision_common import vision_json as vision_fn  # noqa: PLC0415
    try:
        reply = vision_fn(
            _MOTION_PROMPT,
            subsample_paths(frame_paths),
            tier="check",
            max_tokens=800,
        )
    except Exception as exc:  # noqa: BLE001 - a failed clip remains auditable
        return {"flag": None, "explanation": f"reqa call failed: {exc}"}
    return {
        "flag": _as_bool(reply.get("has_motion_error")),
        "explanation": str(reply.get("explanation", "")),
    }


def flag_rate(verdicts: list[dict]) -> float:
    """Fraction flagged among known verdicts; missing calls do not count."""
    known = [v for v in verdicts if v.get("flag") is not None]
    if not known:
        return float("nan")
    return sum(1 for verdict in known if verdict["flag"]) / len(known)
