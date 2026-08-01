"""Protected HTTP API for durable user-scoped session retrieval."""
from __future__ import annotations

import copy
import pathlib

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import StreamingResponse

from service.core.auth import CurrentUser, require_current_user
from service.session_history.adapters import (
    ArtifactDeletionError,
    InvalidCursor,
    SessionDeleteConflict,
)
from service.session_history.dependencies import (
    get_history_artifacts,
    get_session_catalog,
)
from service.session_history.models import (
    SessionListResponse,
    SessionSummary,
    SessionTitleRequest,
    WorkspaceHydration,
)


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


@router.post("", response_model=SessionSummary, status_code=201)
def create_session(
    payload: SessionTitleRequest,
    user: CurrentUser = Depends(require_current_user),
    catalog=Depends(get_session_catalog),
):
    return catalog.create_for_owner(user.sub, title=payload.title).summary


@router.get("/{pid}", response_model=SessionSummary)
def get_session(
    pid: str,
    user: CurrentUser = Depends(require_current_user),
    catalog=Depends(get_session_catalog),
):
    session = catalog.get_owned(pid, user.sub)
    if session is None:
        raise HTTPException(status_code=404, detail="Session not found")
    return session.summary


@router.patch("/{pid}", response_model=SessionSummary)
def rename_session(
    pid: str,
    payload: SessionTitleRequest,
    user: CurrentUser = Depends(require_current_user),
    catalog=Depends(get_session_catalog),
):
    session = catalog.rename_owned(pid, user.sub, title=payload.title)
    if session is None:
        raise HTTPException(status_code=404, detail="Session not found")
    return session.summary


@router.delete("/{pid}", status_code=204)
def delete_session(
    pid: str,
    request: Request,
    user: CurrentUser = Depends(require_current_user),
    catalog=Depends(get_session_catalog),
    artifacts=Depends(get_history_artifacts),
):
    try:
        session = catalog.begin_delete_complete_owned(pid, user.sub)
    except SessionDeleteConflict as exc:
        raise HTTPException(
            status_code=409, detail="Only completed sessions can be deleted"
        ) from exc
    if session is None:
        raise HTTPException(status_code=404, detail="Session not found")

    try:
        artifacts.delete_prefix(f"artifacts/{pid}/")
    except ArtifactDeletionError as exc:
        try:
            catalog.restore_delete_complete_owned(pid, user.sub)
        except Exception:  # pragma: no cover - the original storage error is primary
            pass
        raise HTTPException(
            status_code=502, detail="Could not delete session artifacts; try again"
        ) from exc

    try:
        catalog.finish_delete_complete_owned(pid, user.sub)
    except Exception as exc:
        raise HTTPException(status_code=500, detail="Could not remove session metadata") from exc

    # A published active-workspace receipt contains no media, but deleting it
    # avoids a later page visit attempting to hydrate the now-deleted PID.
    active_workspaces = getattr(request.app.state, "active_workspaces", None)
    if active_workspaces is not None:
        manifest = active_workspaces.get(user.sub)
        if manifest and manifest.state == "published" and manifest.published_pid == pid:
            active_workspaces.discard(user.sub, manifest.workspace_id)


def _workspace_artifact_url(pid: str, session, value) -> str | None:
    if not isinstance(value, str):
        return None
    name = pathlib.PurePosixPath(value).name
    if name != value or name not in session.artifact_keys:
        return None
    return f"/sessions/{pid}/artifacts/{name}"


@router.get("/{pid}/workspace", response_model=WorkspaceHydration)
def get_workspace(
    pid: str,
    user: CurrentUser = Depends(require_current_user),
    catalog=Depends(get_session_catalog),
    artifacts=Depends(get_history_artifacts),
):
    session = catalog.get_owned(pid, user.sub)
    if (
        session is None
        or not session.summary.workspace_available
        or session.snapshot_key is None
    ):
        raise HTTPException(status_code=404, detail="Session workspace not found")
    snapshot = artifacts.get_workspace(session.snapshot_key)
    if snapshot is None or snapshot.schema_version != session.snapshot_version:
        raise HTTPException(status_code=404, detail="Session workspace not found")

    value = copy.deepcopy(snapshot.model_dump())
    for pair in value["pairs"]:
        pair["mid_url"] = _workspace_artifact_url(
            pid, session, pair.get("mid_url")
        )
    result = value["result"]
    result["artifacts"] = {
        name: url
        for name, basename in result.get("artifacts", {}).items()
        if (url := _workspace_artifact_url(pid, session, basename)) is not None
    }
    for field in ("pair_mids", "key_urls"):
        result[field] = {
            index: url
            for index, basename in result.get(field, {}).items()
            if (url := _workspace_artifact_url(pid, session, basename)) is not None
        }
    for explanation in result.get("explanations", {}).values():
        if isinstance(explanation, dict) and "annotated_url" in explanation:
            explanation["annotated_url"] = _workspace_artifact_url(
                pid, session, explanation.get("annotated_url")
            )
    transcript = (
        artifacts.get_transcript(session.message_snapshot_key)
        if session.message_snapshot_key is not None
        else None
    )
    value["qa"] = [turn.model_dump() for turn in (transcript.turns if transcript else [])]
    return WorkspaceHydration.model_validate(value)


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
