"""Session feature API: POST /session, /session/video, and planted demos.
and the planted-error demo endpoints. All funnel into streaming.stream_session."""
from __future__ import annotations

from typing import List

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile

from service.core.dependencies import get_session_repository
from service.media.ingest import _load_frames_from_video, _load_keys
from service.sessions.repository import SessionRepository
from service.sessions.streaming import stream_session

router = APIRouter()


@router.post("/session")
async def post_session(
    keys: List[UploadFile] = File(...),
    engines: str = Form("stub"),
    cadence: int = Form(12),
    smoothness: int = Form(2),
    show: str = Form(""),
    repository: SessionRepository = Depends(get_session_repository),
):
    if len(keys) < 2:
        raise HTTPException(status_code=400, detail="Need >= 2 key frames")
    return stream_session(_load_keys(keys), engines, cadence_fps=cadence,
                          smoothness=smoothness, show=show or None,
                          repository=repository)


@router.post("/session/video")
async def post_session_video(
    video: UploadFile = File(...),
    stride: int = Form(2),
    engines: str = Form("stub"),
    cadence: int = Form(12),
    smoothness: int = Form(2),
    show: str = Form(""),
    repository: SessionRepository = Depends(get_session_repository),
):
    """Drop-a-video session: decode the upload, keep every `stride`-th frame as the
    artist's keys, then run the SAME co-pilot session as POST /session. `cadence` (the
    form default) is IGNORED here — the artist's actual keying rate is derived from the
    clip's own native fps / effective stride, not guessed, so the badge reflects reality."""
    key_arrays, eff_stride, source_frames, source_fps = _load_frames_from_video(video, stride)
    cadence_fps = round(source_fps / eff_stride) or 1
    sampling = {
        "source_frames": source_frames,
        "requested_stride": stride,
        "stride": eff_stride,          # > requested when the clip was lightly auto-fit
        "kept": len(key_arrays),
    }
    return stream_session(key_arrays, engines, cadence_fps=cadence_fps,
                           smoothness=smoothness, sampling=sampling, show=show or None,
                           repository=repository)


@router.get("/session/planted/cases")
def get_planted_cases():
    """Case list for the UI's planted-demo picker (labeled demo — see service/planted.py)."""
    from service.media.planted import list_cases
    return {"cases": list_cases()}


@router.post("/session/planted")
def post_session_planted(case: str = Form(...), engines: str = Form("box"),
                         cadence: int = Form(12), smoothness: int = Form(2),
                         repository: SessionRepository = Depends(get_session_repository)):
    """PLANTED-ERROR demo session: a stored bad in-between from a frozen suite is planted
    as the pair's fill, then the REAL QA/perception/annotate path judges it. Exists because
    the live path yields no natural flags (the gate refuses ghost-prone pairs — probed
    n=9+n=40); every event carries `planted` metadata so the UI labels it honestly."""
    from service.media.planted import load_case, planted_overrides
    try:
        keys, mid, meta = load_case(case)
    except KeyError:
        raise HTTPException(status_code=404, detail=f"unknown planted case {case!r}")
    except FileNotFoundError as exc:
        raise HTTPException(status_code=503, detail=str(exc))
    return stream_session(keys, engines, cadence_fps=cadence, smoothness=smoothness,
                           sampling=meta, eng_override=planted_overrides(mid),
                           repository=repository)
