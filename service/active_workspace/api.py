"""HTTP API for the active workspace — the four routes the deployed UI calls.

Shapes are dictated by the shipped client, not chosen here. See models.py for
which client behaviour each field feeds.
"""
from __future__ import annotations

import json
import time

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from fastapi.responses import StreamingResponse

from service.active_workspace.dependencies import (
    get_active_workspace_max_idle,
    get_active_workspace_service,
)
from service.active_workspace.models import WorkspaceEvent
from service.core.auth import CurrentUser, require_current_user


router = APIRouter(prefix="/active-workspace", tags=["active-workspace"])

NOT_FOUND = "Active workspace not found"


def _frame(event: WorkspaceEvent) -> str:
    """One SSE frame.

    `id:` is not decoration. The client reads it back as `lastEventId` and drops
    any frame whose id is <= the cursor it sent; with no id the browser reports
    an empty string, `Number("")` is 0, and every frame it receives looks stale.
    """
    return (f"id: {event.sequence}\n"
            f"event: {event.name}\n"
            f"data: {json.dumps(event.data, ensure_ascii=False)}\n\n")


def _is_terminal(event: WorkspaceEvent) -> bool:
    """The client closes its EventSource on exactly these, so the server should
    stop writing at the same point rather than hold a connection nobody reads."""
    return event.name == "error" or (
        event.name == "publish" and event.data.get("published") is True)


@router.get("")
def get_active_workspace(
    user: CurrentUser = Depends(require_current_user),
    service=Depends(get_active_workspace_service),
):
    if service is None:
        return {"workspace": None}
    return service.active_response(user.sub)


@router.get("/{workspace_id}/stream")
def stream_active_workspace(
    workspace_id: str,
    after: int = Query(0, ge=0),
    user: CurrentUser = Depends(require_current_user),
    service=Depends(get_active_workspace_service),
    max_idle: float = Depends(get_active_workspace_max_idle),
):
    if service is None or service.get(workspace_id, user.sub) is None:
        raise HTTPException(status_code=404, detail=NOT_FOUND)

    poll = min(0.25, max(0.01, max_idle / 4))

    def generate():
        cursor, idle = after, 0.0
        while True:
            events = service.events_after(workspace_id, user.sub, after=cursor)
            if events is None:       # discarded by its owner mid-stream
                return
            if events:
                idle = 0.0
                for event in events:
                    cursor = event.sequence
                    yield _frame(event)
                    if _is_terminal(event):
                        return
                continue
            if idle >= max_idle:
                return
            time.sleep(poll)
            idle += poll
            yield ": ping\n\n"

    return StreamingResponse(generate(), media_type="text/event-stream")


@router.post("/{workspace_id}/publish")
def publish_active_workspace(
    workspace_id: str,
    user: CurrentUser = Depends(require_current_user),
    service=Depends(get_active_workspace_service),
):
    """A failed publish is a 200 carrying `published: false`, not a 5xx.

    The client reads `error` off the body and offers "Finish saving your
    session"; an HTTP error would instead surface as "Publish retry failed"
    with nothing to retry against.
    """
    if service is None:
        raise HTTPException(status_code=404, detail=NOT_FOUND)
    outcome = service.publish(workspace_id, user.sub)
    if outcome is None:
        raise HTTPException(status_code=404, detail=NOT_FOUND)
    return outcome


@router.delete("/{workspace_id}", status_code=204)
def discard_active_workspace(
    workspace_id: str,
    user: CurrentUser = Depends(require_current_user),
    service=Depends(get_active_workspace_service),
):
    if service is None or not service.discard(workspace_id, user.sub):
        raise HTTPException(status_code=404, detail=NOT_FOUND)
    return Response(status_code=204)
