"""Self-QA decision for one in-between: pass or flag-for-review.

OR-union of the Qwen3-VL detector verdict and the reference-free interp-softness
signal — the validated small-gap fusion (recall 0.42->0.78 @ ~0.90 precision).
This never drops or ships silently: a flag routes the frame to the artist.
"""
from __future__ import annotations

from inbetween_copilot.domain.states import QAStatus
from inbetween_copilot.qa.models import FrameQA
from inbetween_copilot.thresholds import TAU_SOFT


def frame_qa(has_error: bool, softness: float, *, tau_soft: float = TAU_SOFT) -> FrameQA:
    reasons = []
    if has_error:
        reasons.append("detector")
    if softness > tau_soft:
        reasons.append(f"softness>{tau_soft}")
    if reasons:
        return FrameQA(status=QAStatus.FLAG, reason="+".join(reasons))
    return FrameQA(status=QAStatus.PASS, reason="")


def frame_qa_from_verdict(verdict) -> FrameQA:
    """Map a calibrated 3-state CSQVerdict to the FrameQA the loop consumes.
    `abstain` is the new trust tier (route to the artist), never silently passed.
    QAStatus deliberately mirrors csq.verdict.Decision — this seam is what keeps
    the pipeline decoupled from the CSQ package."""
    decision = getattr(verdict, "decision", QAStatus.FLAG)
    reason = f"csq:{decision} p={verdict.p_error:.2f} u={verdict.u:.2f}"
    detail = str(getattr(verdict, "explanation", "") or "").strip()
    if detail:
        reason = f"{reason} {detail}"
    return FrameQA(status=QAStatus(decision), reason=reason,
                   p_error=float(verdict.p_error), u=float(verdict.u))
