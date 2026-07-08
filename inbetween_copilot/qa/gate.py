"""Self-QA decision for one in-between: pass or flag-for-review.

OR-union of the Qwen3-VL detector verdict and the reference-free interp-softness
signal — the validated small-gap fusion (recall 0.42->0.78 @ ~0.90 precision).
This never drops or ships silently: a flag routes the frame to the artist.
"""
from __future__ import annotations

from dataclasses import dataclass

from inbetween_copilot.pipeline.states import QAStatus


@dataclass(frozen=True)
class FrameQA:
    status: str   # QAStatus value ("pass" | "flag" | "abstain"; abstain = calibrated path only)
    reason: str
    # Typed CSQ numbers (P2+D, 2026-07-08): the service used to regex-parse these
    # back OUT of the reason string ("csq:… p=… u=…") — a reformat silently killed
    # the UI confidence meter. The note stays human-readable; the numbers ride typed.
    p_error: "float | None" = None
    u: "float | None" = None


def frame_qa(has_error: bool, softness: float, *, tau_soft: float = 0.15) -> FrameQA:
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
    return FrameQA(status=QAStatus(decision), reason=reason,
                   p_error=float(verdict.p_error), u=float(verdict.u))
