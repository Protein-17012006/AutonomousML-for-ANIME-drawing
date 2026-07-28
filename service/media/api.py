"""Media demo API: decimate-vs-GT comparison (synchronous, RIFE-bound)."""
from __future__ import annotations

from typing import List

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile

from service.core.auth import request_user_sub
from service.core.config import default_engine
from service.core.errors import RuntimeBusy, UnknownEngine
from service.core.http import model_or_422
from service.infrastructure.admission import engine_admission
from service.infrastructure.engines import resolve
from service.media.demo import build_demo_videos
from service.media.ingest import _load_keys
from service.sessions.repository import SessionRepository
from service.sessions.http_dependencies import get_session_repository
from service.sessions.schemas import SessionCfg

router = APIRouter()


@router.post("/demo")
def post_demo(
    request: Request,
    frames: List[UploadFile] = File(...),
    engines: str | None = Form(None),
    interpolator: str = Form("rife"),
    cadence: int = Form(12),
    smoothness: int = Form(2),
    repository: SessionRepository = Depends(get_session_repository),
):
    """Decimate-vs-GT demo: upload a FULL ordered cut -> stride-2 decimate (even=keys,
    odd=hidden GT) -> RIFE the mids -> one side-by-side compare.mp4 (left GOC / right
    RIFE). Synchronous (RIFE-bound); runs in Starlette's threadpool (sync def).
    `cadence`/`smoothness` derive the render fps the SAME way a real session does
    (SessionCfg.fps = cadence_fps * smoothness) — the web UI's demo pane posts these
    from the same on-screen engine/cadence/smoothness controls a live run uses, so the
    compare video's rate matches what the artist picked instead of a fixed 24fps."""
    if len(frames) < 3:
        raise HTTPException(status_code=400, detail="Need >= 3 frames for the decimate-vs-GT demo")
    full = _load_keys(frames)

    selected_engine = engines or default_engine()
    cfg = model_or_422(
        SessionCfg,
        engines=selected_engine,
        interpolator=interpolator,
        cadence_fps=cadence,
        smoothness=smoothness,
    )
    try:
        controller = engine_admission(selected_engine)
    except UnknownEngine as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    try:
        lease = controller.acquire()
    except RuntimeBusy as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc

    sid = None
    try:
        eng = resolve(selected_engine, interpolator=cfg.interpolator)
        interpolation_engine = eng.rife_engine
        if interpolation_engine is None:
            raise HTTPException(
                status_code=400,
                detail=(
                    f"engines {selected_engine!r} has no interpolation engine"
                ),
            )

        sid, session_dir = repository.create("copilot_demo", pin=True)
        owner_sub = request_user_sub(request)
        if owner_sub:
            repository.set_owner(sid, owner_sub)
        build_demo_videos(
            full, interpolation_engine, session_dir, fps=cfg.fps
        )
        return {
            "video": f"/session/{sid}/compare.mp4",
            "video_orig": f"/session/{sid}/original.mp4",
            "video_rife": f"/session/{sid}/recon.mp4",
            "frames": len(full),
            "src": len(full[0::2]),
            "gt": len(full[1::2]),
            "interpolator": cfg.interpolator,
        }
    finally:
        if sid is not None:
            repository.unpin(sid)
        lease.release()
