"""Self-QA decision for one in-between: pass or flag-for-review.

OR-union of the Qwen3-VL detector verdict and the reference-free interp-softness
signal — the validated small-gap fusion (recall 0.42->0.78 @ ~0.90 precision).
This never drops or ships silently: a flag routes the frame to the artist.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class FrameQA:
    status: str   # "pass" | "flag" | "abstain" (abstain only from the calibrated path)
    reason: str


def frame_qa(has_error: bool, softness: float, *, tau_soft: float = 0.15) -> FrameQA:
    reasons = []
    if has_error:
        reasons.append("detector")
    if softness > tau_soft:
        reasons.append(f"softness>{tau_soft}")
    if reasons:
        return FrameQA(status="flag", reason="+".join(reasons))
    return FrameQA(status="pass", reason="")


def frame_qa_from_verdict(verdict) -> FrameQA:
    """Map a calibrated 3-state QAVerdict to the FrameQA the loop consumes.
    `abstain` is the new trust tier (route to the artist), never silently passed."""
    decision = getattr(verdict, "decision", "flag")
    reason = f"csq:{decision} p={verdict.p_error:.2f} u={verdict.u:.2f}"
    return FrameQA(status=decision, reason=reason)
