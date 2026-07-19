"""Protected HTTP API for durable user-scoped session retrieval."""
from __future__ import annotations

import pathlib

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse

from service.core.auth import CurrentUser, require_current_user
from service.session_history.adapters import InvalidCursor
from service.session_history.dependencies import (
    get_history_artifacts,
    get_session_catalog,
)
from service.session_history.models import SessionListResponse


router = APIRouter(prefix="/sessions", tags=["session-history"])


@router.get("", response_model=SessionListResponse)
def list_sessions(
    limit: int = Query(20, ge=1, le=100),
    cursor: str | None = Query(None, max_length=256),
    user: CurrentUser = Depends(require_current_user),
    catalog=Depends(get_session_catalog),
):
    try:
        page = catalog.list_for_owner(user.sub, limit=limit, cursor=cursor)
    except InvalidCursor as exc:
        raise HTTPException(status_code=400, detail="Invalid session cursor") from exc
    return SessionListResponse(
        items=[item.summary for item in page.items],
        next_cursor=page.next_cursor,
    )


@router.get("/{pid}/artifacts/{name}")
def get_artifact(
    pid: str,
    name: str,
    user: CurrentUser = Depends(require_current_user),
    catalog=Depends(get_session_catalog),
    artifacts=Depends(get_history_artifacts),
):
    if pathlib.PurePosixPath(name).name != name or pathlib.PurePosixPath(name).suffix.lower() not in {
        ".png", ".md", ".mp4"
    }:
        raise HTTPException(status_code=404, detail="Session artifact not found")
    session = catalog.get_owned(pid, user.sub)
    if session is None:
        raise HTTPException(status_code=404, detail="Session artifact not found")
    key = session.artifact_keys.get(name)
    if key is None:
        raise HTTPException(status_code=404, detail="Session artifact not found")
    stored = artifacts.get(key, filename=name)
    if stored is None:
        raise HTTPException(status_code=404, detail="Session artifact not found")
    headers = {"Content-Disposition": f'inline; filename="{stored.filename}"'}
    if stored.content_length is not None:
        headers["Content-Length"] = str(stored.content_length)
    return StreamingResponse(
        stored.body,
        media_type=stored.content_type or "application/octet-stream",
        headers=headers,
    )
