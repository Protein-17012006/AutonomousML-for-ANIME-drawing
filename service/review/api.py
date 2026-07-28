"""Thin HTTP adapter for finished-session review and correction use cases."""
from __future__ import annotations

import os
import pathlib
import shutil
import tempfile
import zipfile

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse

from service.core.auth import request_user_sub
from service.core.errors import (
    InvalidGapIndex, InvalidKeyImage, RuntimeBusy, SessionNotFound,
)
from service.review.http_dependencies import (
    ReviewHttpRuntime,
    get_review_http_runtime,
)
from service.sessions.http_dependencies import (
    SessionHttpRuntime,
    get_session_http_runtime,
    get_session_repository,
)
from service.sessions.repository import SessionRepository
from service.sessions.schemas import PairEvent, ResultEvent


router = APIRouter()


class _SnapshotFileResponse(FileResponse):
    """Delete the download snapshot even when the client disconnects mid-send."""

    def __init__(self, path, *, snapshot_dir: pathlib.Path, **kwargs):
        super().__init__(path, **kwargs)
        self._snapshot_dir = snapshot_dir

    async def __call__(self, scope, receive, send):
        try:
            await super().__call__(scope, receive, send)
        finally:
            # Starlette background tasks run only after a successful body send.
            # A transport exception must not turn aborted downloads into an
            # unbounded temp-disk leak outside the session retention cap.
            shutil.rmtree(self._snapshot_dir, ignore_errors=True)


@router.post("/session/{sid}/rerun")
def post_rerun(sid: int, request: Request, engines: str | None = Form(None),
               interpolator: str | None = Form(None),
               cadence: int | None = Form(None),
               smoothness: int | None = Form(None),
               sessions: SessionRepository = Depends(get_session_repository),
               session_runtime: SessionHttpRuntime = Depends(get_session_http_runtime),
               review_runtime: ReviewHttpRuntime = Depends(get_review_http_runtime)):
    try:
        state = review_runtime.review_for(sessions).state(sid)
    except SessionNotFound as exc:
        raise HTTPException(status_code=404, detail="Unknown session (or no result yet)") from exc
    cfg = state["cfg"]
    return session_runtime.stream_session(
        state["keys"],
        engines if engines is not None else cfg.engines,
        interpolator=(
            interpolator if interpolator is not None else cfg.interpolator
        ),
        cadence_fps=cadence if cadence is not None else cfg.cadence_fps,
        smoothness=smoothness if smoothness is not None else cfg.smoothness,
        sampling=dict(state.get("sampling") or {}),
        show=cfg.show,
        repository=sessions,
        owner_sub=request_user_sub(request),
    )


@router.get("/session/{sid}/{name}")
def get_artifact(sid: int, name: str,
                 sessions: SessionRepository = Depends(get_session_repository),
                 runtime: ReviewHttpRuntime = Depends(get_review_http_runtime)):
    download_dir: pathlib.Path | None = None
    try:
        # Serialize with review's directory-generation swap and pin against
        # retention while making a download-owned snapshot. The response then
        # no longer depends on a live session path, so client disconnects cannot
        # strand a repository pin and later eviction cannot truncate the file.
        with sessions.session_transaction(sid):
            base = runtime.review_for(sessions).artifact_dir(sid)
            download_dir = pathlib.Path(tempfile.mkdtemp(prefix="copilot_download_"))

            if name == "bundle.zip":
                download_path = download_dir / "copilot_session.zip"
                with zipfile.ZipFile(
                        download_path, "w", zipfile.ZIP_DEFLATED) as archive:
                    for file in sorted(base.iterdir()):
                        if (file.is_file()
                                and file.suffix.lower() in {".mp4", ".png", ".md"}):
                            archive.write(file, arcname=file.name)
                response = _SnapshotFileResponse(
                    str(download_path),
                    snapshot_dir=download_dir,
                    media_type="application/zip",
                    filename="copilot_session.zip",
                )
            else:
                path = (base / name).resolve()
                if base not in path.parents and path != base:
                    raise HTTPException(status_code=400, detail="invalid artifact name")
                if not path.is_file():
                    raise HTTPException(status_code=404, detail="Artifact not found")
                download_path = download_dir / path.name
                try:
                    os.link(path, download_path)
                except OSError:
                    shutil.copy2(path, download_path)
                response = _SnapshotFileResponse(
                    str(download_path),
                    snapshot_dir=download_dir,
                )
        return response
    except (KeyError, SessionNotFound) as exc:
        if download_dir is not None:
            shutil.rmtree(download_dir, ignore_errors=True)
        raise HTTPException(status_code=404, detail="Session not found") from exc
    except Exception:
        if download_dir is not None:
            shutil.rmtree(download_dir, ignore_errors=True)
        raise


@router.post("/session/{sid}/key")
def post_key(sid: int, index: int = Form(...), key: UploadFile = File(...),
             sessions: SessionRepository = Depends(get_session_repository),
             runtime: ReviewHttpRuntime = Depends(get_review_http_runtime)):
    lease = None
    pinned = False
    try:
        # Decode before consuming scarce runtime capacity, then pin the parent
        # session for the full queued/run/render transaction so retention cannot
        # evict its state or artifact directory halfway through review.
        drawn = runtime.load_image(key)
        review = runtime.review_for(sessions)
        state = review.state(sid)
        sessions.pin(sid)
        pinned = True
        lease = runtime.admission_for(state["cfg"].engines).acquire()
        outcome = review.add_key(sid, index, drawn)
        return {
            "pairs": [
                PairEvent.from_pair(
                    pair,
                    mid_url=outcome.pair_mids.get(str(pair.index)),
                ).model_dump()
                for pair in outcome.result.pairs
            ],
            "result": ResultEvent.from_result(
                outcome.result,
                outcome.artifact_urls,
                explanations=outcome.explanations,
                pair_mids=outcome.pair_mids,
                key_urls=outcome.key_urls,
                sampling=outcome.sampling,
                csq=outcome.csq,
                qa_degraded=outcome.qa_degraded,
            ).model_dump(),
        }
    except SessionNotFound as exc:
        raise HTTPException(
            status_code=404, detail="Session not found (run a session first)") from exc
    except KeyError as exc:
        raise HTTPException(
            status_code=404, detail="Session not found (run a session first)") from exc
    except RuntimeBusy as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except InvalidGapIndex as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except InvalidKeyImage as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    finally:
        if lease is not None:
            lease.release()
        if pinned:
            sessions.unpin(sid)
