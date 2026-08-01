"""Session feature API: POST /session and /session/video.
Both funnel into streaming.stream_session."""
from __future__ import annotations

from typing import List
import pathlib

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile

from service.active_workspace.dependencies import get_active_workspace_service
from service.core.auth import request_user_sub
from service.core.config import default_engine
from service.sessions.http_dependencies import (
    SessionHttpRuntime,
    get_session_http_runtime,
    get_session_repository,
)
from service.sessions.repository import SessionRepository

router = APIRouter()


def _owned_draft_pid(request: Request, pid: str | None, owner_sub: str | None) -> str | None:
    if not pid:
        return None
    if owner_sub is None:
        raise HTTPException(status_code=401, detail="Authentication required")
    catalog = getattr(request.app.state, "session_catalog", None)
    if catalog is None:
        raise HTTPException(status_code=503, detail="session history is not configured")
    session = catalog.get_owned(pid, owner_sub)
    if session is None:
        raise HTTPException(status_code=404, detail="Session not found")
    if session.summary.status != "draft":
        raise HTTPException(status_code=409, detail="Session is already complete")
    return pid


def _captured_uploads(uploads, *, wanted: bool) -> list[tuple[str, bytes, str]]:
    """The raw bytes of what the artist uploaded, re-wound for the ingest path.

    Only collected for a signed-in run with a workspace to hold them, because it
    is a second copy in memory and nothing anonymous will ever read it back.
    """
    if not wanted:
        return []
    captured = []
    for item in uploads:
        try:
            item.file.seek(0)
            data = item.file.read()
            item.file.seek(0)
        except Exception:                       # noqa: BLE001 — never block a run
            continue
        captured.append((_safe_filename(item.filename), data,
                         item.content_type or "application/octet-stream"))
    return captured


def _safe_filename(value: str | None) -> str:
    name = pathlib.PurePath(value or "upload").name
    return name[:128] or "upload"


@router.post("/session")
def post_session(
    request: Request,
    keys: List[UploadFile] = File(...),
    engines: str | None = Form(None),
    interpolator: str = Form("rife"),
    cadence: int = Form(12),
    smoothness: int = Form(2),
    show: str = Form(""),
    history_pid: str | None = Form(None, max_length=128),
    repository: SessionRepository = Depends(get_session_repository),
    runtime: SessionHttpRuntime = Depends(get_session_http_runtime),
):
    if len(keys) < 2:
        raise HTTPException(status_code=400, detail="Need >= 2 key frames")
    selected_engine = engines or default_engine()
    owner_sub = request_user_sub(request)
    durable_pid = _owned_draft_pid(request, history_pid, owner_sub)
    workspaces = get_active_workspace_service(request)
    captured = _captured_uploads(
        keys, wanted=bool(owner_sub and workspaces is not None))
    return runtime.stream_session(
        runtime.load_keys(keys), selected_engine, interpolator=interpolator,
        cadence_fps=cadence, smoothness=smoothness, show=show or None,
        repository=repository, owner_sub=owner_sub, history_pid=durable_pid,
        workspace_service=workspaces,
        workspace_assets=captured,
        workspace_input={
            "mode": "frames",
            "label": f"{len(keys)} keyframes",
            "filenames": [_safe_filename(item.filename) for item in keys],
        },
    )


@router.post("/session/video")
def post_session_video(
    request: Request,
    video: UploadFile = File(...),
    stride: int = Form(2),
    engines: str | None = Form(None),
    interpolator: str = Form("rife"),
    cadence: int = Form(12),
    smoothness: int = Form(2),
    show: str = Form(""),
    history_pid: str | None = Form(None, max_length=128),
    repository: SessionRepository = Depends(get_session_repository),
    runtime: SessionHttpRuntime = Depends(get_session_http_runtime),
):
    """Drop-a-video session: decode the upload, keep every `stride`-th frame as the
    artist's keys, then run the SAME co-pilot session as POST /session. `cadence` (the
    form default) is IGNORED here — the artist's actual keying rate is derived from the
    clip's own native fps / effective stride, not guessed, so the badge reflects reality."""
    owner_sub = request_user_sub(request)
    durable_pid = _owned_draft_pid(request, history_pid, owner_sub)
    workspaces = get_active_workspace_service(request)
    captured = _captured_uploads(
        [video], wanted=bool(owner_sub and workspaces is not None))
    key_arrays, gt_frames, eff_stride, source_frames, source_fps = runtime.load_video_keys(
        video, stride)
    cadence_fps = round(source_fps / eff_stride) or 1
    sampling = {
        "source_frames": source_frames,
        "requested_stride": stride,
        "stride": eff_stride,          # > requested when the clip was lightly auto-fit
        "kept": len(key_arrays),
    }
    selected_engine = engines or default_engine()
    return runtime.stream_session(
        key_arrays, selected_engine, interpolator=interpolator,
        cadence_fps=cadence_fps,
        smoothness=smoothness, sampling=sampling, show=show or None,
        gt_frames=gt_frames,
        repository=repository, owner_sub=owner_sub, history_pid=durable_pid,
        workspace_service=workspaces,
        workspace_assets=captured,
        workspace_input={
            "mode": "video",
            "label": _safe_filename(video.filename),
            "filenames": [_safe_filename(video.filename)],
        },
    )
