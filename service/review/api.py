"""Thin HTTP adapter for finished-session review and correction use cases."""
from __future__ import annotations

import io
import zipfile

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse, StreamingResponse

from service.core.dependencies import get_session_repository
from service.core.errors import InvalidGapIndex, SessionNotFound
from service.review.service import ReviewSession
from service.sessions.repository import SessionRepository
from service.sessions.streaming import stream_session


router = APIRouter()


@router.post("/session/{sid}/rerun")
def post_rerun(sid: int, engines: str | None = Form(None),
               cadence: int | None = Form(None),
               smoothness: int | None = Form(None),
               sessions: SessionRepository = Depends(get_session_repository)):
    try:
        state = ReviewSession(sessions).state(sid)
    except SessionNotFound as exc:
        raise HTTPException(status_code=404, detail="Unknown session (or no result yet)") from exc
    cfg = state["cfg"]
    return stream_session(
        state["keys"],
        engines if engines is not None else cfg.engines,
        cadence_fps=cadence if cadence is not None else cfg.cadence_fps,
        smoothness=smoothness if smoothness is not None else cfg.smoothness,
        repository=sessions,
    )


@router.get("/session/{sid}/{name}")
async def get_artifact(sid: int, name: str,
                       sessions: SessionRepository = Depends(get_session_repository)):
    try:
        base = ReviewSession(sessions).artifact_dir(sid)
    except SessionNotFound as exc:
        raise HTTPException(status_code=404, detail="Session not found") from exc

    if name == "bundle.zip":
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
            for file in sorted(base.iterdir()):
                if file.is_file() and file.suffix.lower() in {".mp4", ".png", ".md"}:
                    archive.write(file, arcname=file.name)
        buffer.seek(0)
        return StreamingResponse(
            buffer,
            media_type="application/zip",
            headers={"Content-Disposition": 'attachment; filename="copilot_session.zip"'},
        )

    path = (base / name).resolve()
    if base not in path.parents and path != base:
        raise HTTPException(status_code=400, detail="invalid artifact name")
    if not path.exists():
        raise HTTPException(status_code=404, detail="Artifact not found")
    return FileResponse(str(path))


@router.post("/session/{sid}/key")
async def post_key(sid: int, index: int = Form(...), key: UploadFile = File(...),
                   sessions: SessionRepository = Depends(get_session_repository)):
    try:
        return ReviewSession(sessions).add_key(sid, index, await key.read())
    except SessionNotFound as exc:
        raise HTTPException(
            status_code=404, detail="Session not found (run a session first)") from exc
    except InvalidGapIndex as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
