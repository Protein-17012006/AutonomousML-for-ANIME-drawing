"""Session feature API: POST /session and /session/video.
Both funnel into streaming.stream_session."""
from __future__ import annotations

from typing import List
import pathlib

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile

from service.core.auth import auth_required, request_user_sub
from service.core.config import default_engine
from service.sessions.http_dependencies import (
    SessionHttpRuntime,
    get_session_http_runtime,
    get_session_repository,
)
from service.sessions.repository import SessionRepository
from service.sessions.resume import NoStoredKeys, stored_key_names

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


def _safe_filename(value: str | None) -> str:
    name = pathlib.PurePath(value or "upload").name
    return name[:128] or "upload"


@router.post("/session/resume/{pid}")
def post_session_resume(
    pid: str,
    request: Request,
    repository: SessionRepository = Depends(get_session_repository),
    runtime: SessionHttpRuntime = Depends(get_session_http_runtime),
):
    """Turn a durable history entry back into a working session.

    History is a projection; the interactive routes read a runtime session that
    lives in this process, is capped and dies with a restart. Without this route
    a reopened session can only be read, which is what the artist met after a
    page reload. Restores inputs and recorded decisions; regenerates nothing.
    """
    owner_sub = request_user_sub(request)
    if owner_sub is None and auth_required():
        raise HTTPException(status_code=401, detail="Authentication required")
    catalog = getattr(request.app.state, "session_catalog", None)
    artifacts = getattr(request.app.state, "history_artifacts", None)
    if catalog is None or artifacts is None:
        raise HTTPException(status_code=503, detail="session history is not configured")
    if runtime.resume_for is None or runtime.load_stored_keys is None:
        raise HTTPException(status_code=503, detail="session runtime is not configured")

    session = catalog.get_owned(pid, owner_sub)
    # 404, never 403: a stranger learns nothing about which pids exist.
    if session is None or session.snapshot_key is None:
        raise HTTPException(status_code=404, detail="Session not found")
    stored = artifacts.get_workspace(session.snapshot_key)
    if stored is None:
        raise HTTPException(status_code=404, detail="Session workspace not found")

    snapshot = stored.model_dump()
    blobs = []
    for name in stored_key_names(snapshot):
        key = session.artifact_keys.get(name)
        artifact = artifacts.get(key, filename=name) if key else None
        if artifact is None:
            raise HTTPException(
                status_code=409,
                detail=f"the stored key frame {name} is missing; this session cannot be resumed",
            )
        blobs.append((name, artifact.body.read()))

    try:
        sid = runtime.resume_for(repository).restore(
            pid, snapshot, runtime.load_stored_keys(blobs),
            owner_sub=owner_sub, default_engines=default_engine(),
        )
    except NoStoredKeys as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return {"sid": sid, "pid": pid}


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
    return runtime.stream_session(
        runtime.load_keys(keys), selected_engine, interpolator=interpolator,
        cadence_fps=cadence, smoothness=smoothness, show=show or None,
        repository=repository, owner_sub=owner_sub, history_pid=durable_pid,
        active_workspace=getattr(request.app.state, "active_workspaces", None),
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
    key_arrays, gt_frames, eff_stride, source_frames, source_fps = runtime.load_video_keys(
        video, stride)
    video.file.seek(0)
    source_video = video.file.read()
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
        active_workspace=getattr(request.app.state, "active_workspaces", None),
        workspace_input={
            "mode": "video",
            "label": _safe_filename(video.filename),
            "filenames": [_safe_filename(video.filename)],
        },
        source_video=source_video,
    )
