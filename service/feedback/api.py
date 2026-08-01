"""Read access to persisted calibration feedback.

Writes are intentionally batch-only and live in ``service.review.api`` because
they must commit alongside the live review-state revision.
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from service.feedback.dependencies import feedback_store_for
from service.feedback.models import FeedbackRecord

router = APIRouter(tags=["feedback"])


class FeedbackListResp(BaseModel):
    feedback: list[FeedbackRecord]


@router.get("/session/{sid}/feedback", response_model=FeedbackListResp)
def list_feedback(sid: int, request: Request):
    try:
        rows = feedback_store_for(request.app).list_session(sid)
    except Exception as exc:
        raise HTTPException(status_code=503, detail="feedback store unavailable") from exc
    return {"feedback": rows}
