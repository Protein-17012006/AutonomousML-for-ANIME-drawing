"""Flag-feedback API: one clip-quality vote per (pair, voter), machine verdict
snapshotted server-side (per-show CSQ calibration data — see the vault design
note 'Animation QA - Flag Feedback (CSQ Calibration) - Design')."""
from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from service.feedback import FeedbackRecord, build_feedback
from service.feedback_store import feedback_store_for
from service.state import _state

router = APIRouter(tags=["feedback"])


class VoteReq(BaseModel):
    pair_index: int
    vote: Literal["up", "down"]


class FeedbackListResp(BaseModel):
    feedback: list[FeedbackRecord]


def _voter(request: Request) -> str:
    user = getattr(request.state, "user", None)
    return user.sub if user is not None else "anon"


@router.post("/session/{sid}/feedback", response_model=FeedbackRecord)
def post_feedback(sid: int, req: VoteReq, request: Request):
    state = _state.get(sid)
    if state is None:
        raise HTTPException(status_code=404, detail="Unknown or expired session")
    try:
        record = build_feedback(state, sid, req.pair_index, req.vote, _voter(request))
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    # config/store-construction errors (e.g. missing COPILOT_FEEDBACK_TABLE) should
    # propagate loudly, not be swallowed as a 503 "outage" — only the actual store
    # operation below is an outage.
    store = feedback_store_for(request.app)
    try:
        return store.upsert(record)
    except Exception as exc:   # store outage: degrade loudly, never 500/never lose silently
        raise HTTPException(status_code=503, detail="feedback store unavailable") from exc


@router.get("/session/{sid}/feedback", response_model=FeedbackListResp)
def list_feedback(sid: int, request: Request):
    store = feedback_store_for(request.app)
    try:
        rows = store.list_session(sid)
    except Exception as exc:
        raise HTTPException(status_code=503, detail="feedback store unavailable") from exc
    return {"feedback": rows}
