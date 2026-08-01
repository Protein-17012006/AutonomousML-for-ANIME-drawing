from __future__ import annotations

import json
import queue
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import FileResponse, StreamingResponse

from service.active_workspace.dependencies import active_workspaces_for
from service.core.auth import CurrentUser, require_current_user

router = APIRouter(prefix="/active-workspace", tags=["active-workspace"])


@router.get("")
def get_active_workspace(request: Request, user: CurrentUser = Depends(require_current_user)):
    manifest = active_workspaces_for(request).get(user.sub)
    if manifest is None:
        return {"workspace": None}
    workspace = manifest.model_dump()
    # URLs are derived at response time, never persisted in the manifest. Each
    # one remains cookie-protected by the artifact handler below.
    workspace["artifact_urls"] = {
        asset.name: f"/active-workspace/{manifest.workspace_id}/artifacts/{asset.name}"
        for asset in manifest.assets
    }
    return {"workspace": workspace}


@router.get("/{workspace_id}/artifacts/{name}")
def get_active_artifact(workspace_id: str, name: str, request: Request, user: CurrentUser = Depends(require_current_user)):
    path = active_workspaces_for(request).artifact(user.sub, workspace_id, name)
    return FileResponse(path)


@router.delete("/{workspace_id}", status_code=204)
def discard_active_workspace(workspace_id: str, request: Request, user: CurrentUser = Depends(require_current_user)):
    active_workspaces_for(request).discard(user.sub, workspace_id)


@router.post("/{workspace_id}/publish")
def retry_publish(workspace_id: str, request: Request, user: CurrentUser = Depends(require_current_user)):
    return active_workspaces_for(request).retry_publish(user.sub, workspace_id)


@router.get("/{workspace_id}/stream")
def stream_active_workspace(workspace_id: str, after: int = 0, request: Request = None, user: CurrentUser = Depends(require_current_user)):
    store = active_workspaces_for(request)
    replay, subscriber = store.subscribe(user.sub, workspace_id, after)

    def generate():
        try:
            for event in replay:
                yield f"id: {event.sequence}\nevent: {event.name}\ndata: {json.dumps(event.data)}\n\n"
            while True:
                try:
                    event = subscriber.get(timeout=15)
                    yield f"id: {event.sequence}\nevent: {event.name}\ndata: {json.dumps(event.data)}\n\n"
                    # A result only means GPU work finished. Keep the recovery
                    # subscription open until the durable publish receipt (or a
                    # terminal error) has been persisted and delivered.
                    if event.name == "error" or (
                        event.name == "publish" and event.data.get("published") is True
                    ):
                        return
                except queue.Empty:
                    yield ": ping\n\n"
        finally:
            store.unsubscribe(workspace_id, subscriber)
    return StreamingResponse(generate(), media_type="text/event-stream")
