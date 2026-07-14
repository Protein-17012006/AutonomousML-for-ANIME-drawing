"""Memory feature API: authenticated, user-controlled long-term memory."""
from __future__ import annotations

import time
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel

from service.core.auth import (CurrentUser, authorize_session_access,
                               require_current_user)
from service.memory.models import (MemoryCandidate, MemoryItem, MemoryStatus,
                                   extract_candidates, new_memory, validate_candidate)
from service.memory.dependencies import memory_store_for
from service.sessions.repository import SessionRepository
from service.sessions.http_dependencies import get_session_repository

router = APIRouter(prefix="/me/memories", tags=["memory"])


class CreateMemoryReq(BaseModel):
    kind: Literal["preference", "show_context"]
    key: str
    value: str
    summary: str | None = None
    source_cid: str | None = None
    source_sid: int | None = None


class PatchMemoryReq(BaseModel):
    value: str | None = None
    summary: str | None = None
    status: MemoryStatus | None = None


class ExtractMemoryReq(BaseModel):
    sid: int
    cid: str | None = None


@router.get("")
def list_memories(request: Request,
                  user: CurrentUser = Depends(require_current_user)):
    return {"memories": [m.model_dump() for m in memory_store_for(request.app).list(user.sub)]}


@router.post("", status_code=201)
def create_memory(req: CreateMemoryReq, request: Request,
                  user: CurrentUser = Depends(require_current_user),
                  sessions: SessionRepository = Depends(get_session_repository)):
    try:
        if req.source_sid is not None:
            authorize_session_access(request, sessions, req.source_sid)
        candidate = MemoryCandidate(kind=req.kind, key=req.key, value=req.value,
                                    evidence="Explicitly saved by the user", confidence=1)
        item = new_memory(candidate, status="confirmed", source_cid=req.source_cid,
                          source_sid=req.source_sid)
        if req.summary:
            item.summary = req.summary.strip()[:360]
        return memory_store_for(request.app).put(user.sub, item).model_dump()
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.patch("/{memory_id}")
def patch_memory(memory_id: str, req: PatchMemoryReq, request: Request,
                 user: CurrentUser = Depends(require_current_user)):
    store = memory_store_for(request.app)
    item = store.get(user.sub, memory_id)
    if item is None:
        raise HTTPException(status_code=404, detail="Memory not found")
    if req.value is not None:
        candidate = validate_candidate(MemoryCandidate(
            kind=item.kind, key=item.key, value=req.value,
            evidence="Edited by the user", confidence=1,
        ))
        item.value = candidate.value
        item.confidence = 1
    if req.summary is not None:
        item.summary = req.summary.strip()[:360]
    if req.status is not None:
        item.status = req.status
    item.updated_at = int(time.time() * 1000)
    try:
        return store.put(user.sub, item).model_dump()
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.delete("/{memory_id}", status_code=204)
def delete_memory(memory_id: str, request: Request,
                  user: CurrentUser = Depends(require_current_user)):
    if not memory_store_for(request.app).delete(user.sub, memory_id):
        raise HTTPException(status_code=404, detail="Memory not found")
    return Response(status_code=204)


@router.post("/extract")
def extract_session_memories(req: ExtractMemoryReq, request: Request,
                             user: CurrentUser = Depends(require_current_user),
                             sessions: SessionRepository = Depends(get_session_repository)):
    authorize_session_access(request, sessions, req.sid)
    state = sessions.state_for(req.sid)
    if state is None:
        raise HTTPException(status_code=404, detail="Unknown live session")
    from service.infrastructure.director_llm import make_ask_fn
    candidates = extract_candidates(state.get("chat", []), make_ask_fn())
    store = memory_store_for(request.app)
    existing = {(m.kind, m.key): m for m in store.list(user.sub)}
    saved = []
    for candidate in candidates:
        old = existing.get((candidate.kind, candidate.key))
        item = new_memory(candidate, status="candidate", source_cid=req.cid,
                          source_sid=req.sid)
        if old is not None:
            item.id, item.created_at = old.id, old.created_at
            # Never silently demote a user-confirmed value. Return the candidate
            # only when it is genuinely new; explicit edits remain authoritative.
            if old.status == "confirmed":
                continue
        try:
            saved.append(store.put(user.sub, item).model_dump())
        except ValueError:
            break
    return {"candidates": saved}
