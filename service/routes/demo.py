"""POST /demo — the decimate-vs-GT compare demo (synchronous, RIFE-bound)."""
from __future__ import annotations

import tempfile
from typing import List

from fastapi import APIRouter, File, Form, HTTPException, UploadFile

from service.demo import build_demo_videos
from service.engines import resolve
from service.ingest import _load_keys
from service.state import _sessions, _sid_counter
from service.streaming import _session_cfg_or_422

router = APIRouter()


@router.post("/demo")
def post_demo(
    frames: List[UploadFile] = File(...),
    engines: str = Form("stub"),
    cadence: int = Form(12),
    smoothness: int = Form(2),
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

    cfg = _session_cfg_or_422(engines=engines, cadence_fps=cadence, smoothness=smoothness)
    eng = resolve(engines, cfg)
    rife = eng.rife_engine
    if rife is None:
        raise HTTPException(status_code=400, detail=f"engines {engines!r} has no rife_engine")

    sid = next(_sid_counter)
    session_dir = tempfile.mkdtemp(prefix=f"copilot_demo_{sid}_")
    _sessions[sid] = session_dir
    build_demo_videos(full, rife, session_dir, fps=cfg.fps)
    return {
        "video": f"/session/{sid}/compare.mp4",          # side-by-side fallback
        "video_orig": f"/session/{sid}/original.mp4",    # the two separate cuts the
        "video_rife": f"/session/{sid}/recon.mp4",        # client before/after wipe needs
        "frames": len(full),
        "src": len(full[0::2]),
        "gt": len(full[1::2]),
    }
