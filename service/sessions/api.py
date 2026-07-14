"""Session feature API: POST /session and /session/video.
Both funnel into streaming.stream_session."""
from __future__ import annotations

from typing import List

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile

from service.core.auth import request_user_sub
from service.core.config import default_engine
from service.sessions.http_dependencies import (
    SessionHttpRuntime,
    get_session_http_runtime,
    get_session_repository,
)
from service.sessions.repository import SessionRepository

router = APIRouter()


@router.post("/session")
def post_session(
    request: Request,
    keys: List[UploadFile] = File(...),
    engines: str | None = Form(None),
    cadence: int = Form(12),
    smoothness: int = Form(2),
    show: str = Form(""),
    repository: SessionRepository = Depends(get_session_repository),
    runtime: SessionHttpRuntime = Depends(get_session_http_runtime),
):
    if len(keys) < 2:
        raise HTTPException(status_code=400, detail="Need >= 2 key frames")
    selected_engine = engines or default_engine()
    return runtime.stream_session(
        runtime.load_keys(keys), selected_engine,
        cadence_fps=cadence, smoothness=smoothness, show=show or None,
        repository=repository, owner_sub=request_user_sub(request),
    )


@router.post("/session/video")
def post_session_video(
    request: Request,
    video: UploadFile = File(...),
    stride: int = Form(2),
    engines: str | None = Form(None),
    cadence: int = Form(12),
    smoothness: int = Form(2),
    show: str = Form(""),
    repository: SessionRepository = Depends(get_session_repository),
    runtime: SessionHttpRuntime = Depends(get_session_http_runtime),
):
    """Drop-a-video session: decode the upload, keep every `stride`-th frame as the
    artist's keys, then run the SAME co-pilot session as POST /session. `cadence` (the
    form default) is IGNORED here — the artist's actual keying rate is derived from the
    clip's own native fps / effective stride, not guessed, so the badge reflects reality."""
    key_arrays, eff_stride, source_frames, source_fps = runtime.load_video_keys(
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
        key_arrays, selected_engine, cadence_fps=cadence_fps,
        smoothness=smoothness, sampling=sampling, show=show or None,
        repository=repository, owner_sub=request_user_sub(request),
    )
