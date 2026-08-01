"""Thin HTTP adapter for finished-session review and correction use cases."""
from __future__ import annotations

import os
import pathlib
import json
import shutil
import tempfile
import zipfile
import queue
import threading

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel

from service.core.auth import request_user_sub
from service.core.errors import (
    InvalidKeyImage, SessionNotFound,
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
from service.sessions.schemas import ErrorEvent, sse
from service.feedback.dependencies import feedback_store_for
from service.feedback.models import build_feedback


router = APIRouter()

# A review edit is a revision of one live session.  Keep the reservation at the
# HTTP boundary: it prevents two browser tabs from both recomputing and then
# racing to publish different revisions of the same PID.
_review_jobs: set[int] = set()
_review_jobs_lock = threading.Lock()


def _reserve_review_job(sid: int, sessions: SessionRepository) -> None:
    with _review_jobs_lock:
        if sid in _review_jobs:
            raise HTTPException(status_code=409, detail="A review update is already running")
        try:
            sessions.pin(sid)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="Unknown or expired session") from exc
        _review_jobs.add(sid)


def _release_review_job(sid: int, sessions: SessionRepository) -> None:
    try:
        sessions.unpin(sid)
    finally:
        with _review_jobs_lock:
            _review_jobs.discard(sid)


class VerdictReq(BaseModel):
    pair_index: int
    verdict: str


class VerdictBatchReq(BaseModel):
    verdicts: list[VerdictReq]


def _outcome_events(outcome):
    for pair in outcome.result.pairs:
        yield sse("pair", PairEvent.from_pair(
            pair, mid_url=outcome.pair_mids.get(str(pair.index))).model_copy(
            update={"artist_verdict": getattr(pair, "artist_verdict", None)}))
    yield sse("result", ResultEvent.from_result(
        outcome.result, outcome.artifact_urls, sid=outcome.sid,
        explanations=outcome.explanations, pair_mids=outcome.pair_mids,
        key_urls=outcome.key_urls, sampling=outcome.sampling,
        csq=outcome.csq, qa_degraded=outcome.qa_degraded))


def _review_stream(job):
    """Run a durable review revision independently of its HTTP subscriber."""
    events = queue.Queue()

    def worker():
        try:
            events.put(("progress", {"phase": "evaluating"}))
            outcome = job()
            events.put(("outcome", outcome))
        except Exception as exc:
            # A disconnected subscriber simply will not consume this event.
            # The worker still completes its durable transaction.
            events.put(("error", str(exc)))
        finally:
            events.put(("done", None))

    thread = threading.Thread(target=worker, name="copilot-review-submit", daemon=True)
    # Start before returning the response. This makes the request a job
    # submission, rather than coupling job creation to the first SSE read.
    thread.start()

    def generate():
        try:
            while True:
                kind, payload = events.get()
                if kind == "progress":
                    yield f"event: progress\ndata: {json.dumps(payload)}\n\n"
                elif kind == "outcome":
                    yield from _outcome_events(payload)
                elif kind == "error":
                    yield sse("error", ErrorEvent(message=payload))
                elif kind == "done":
                    return
        finally:
            # Disconnecting only detaches this subscriber. The worker owns the
            # session pin/GPU lease until its durable revision is committed.
            thread.join(timeout=0.1)
    return StreamingResponse(generate(), media_type="text/event-stream")


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


@router.post("/session/{sid}/keys")
def post_keys(sid: int, request: Request, indices: list[int] = Form(...), keys: list[UploadFile] = File(...),
              sessions: SessionRepository = Depends(get_session_repository),
              runtime: ReviewHttpRuntime = Depends(get_review_http_runtime)):
    if len(indices) != len(keys):
        raise HTTPException(status_code=422, detail="Each submitted key needs an index")
    try:
        drawn = [(index, runtime.load_image(key)) for index, key in zip(indices, keys)]
        state = runtime.review_for(sessions).state(sid)
    except SessionNotFound as exc:
        raise HTTPException(status_code=404, detail="Session not found (run a session first)") from exc
    except InvalidKeyImage as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    pid = state.get("published_pid")
    if not isinstance(pid, str) or not pid:
        raise HTTPException(status_code=409, detail="Session is still being saved")
    workspace_input = state.get("workspace_input") or {}
    owner_sub = request_user_sub(request)
    _reserve_review_job(sid, sessions)

    def job():
        try:
            lease = runtime.admission_for(state["cfg"].engines).acquire()
            try:
                outcome = runtime.review_for(sessions).add_keys(sid, drawn)
                published = runtime.publish_review(
                    sid, runtime.review_for(sessions).artifact_dir(sid), outcome,
                    owner_sub=owner_sub, pid=pid, workspace_input=workspace_input)
                if not published.get("published"):
                    raise RuntimeError(published.get("error") or "Could not save review revision")
                return outcome
            finally:
                lease.release()
        finally:
            _release_review_job(sid, sessions)

    return _review_stream(job)


@router.post("/session/{sid}/feedback/batch")
def post_feedback_batch(sid: int, request: Request, payload: VerdictBatchReq,
                        sessions: SessionRepository = Depends(get_session_repository),
                        runtime: ReviewHttpRuntime = Depends(get_review_http_runtime)):
    values = {item.pair_index: item.verdict for item in payload.verdicts}
    if not values or len(values) != len(payload.verdicts) or any(v not in {"accept", "reject"} for v in values.values()):
        raise HTTPException(status_code=422, detail="Submit distinct accept or reject verdicts")
    state = sessions.state_for(sid)
    if state is None:
        raise HTTPException(status_code=404, detail="Unknown or expired session")
    required = {
        pair.index
        for pair in state["result"].pairs
        if pair.action != "needs_key"
        and getattr(pair, "artist_verdict", None) is None
        and getattr(getattr(pair, "qa", None), "status", None) in {"abstain", "flag"}
    }
    if set(values) != required:
        raise HTTPException(
            status_code=422,
            detail="Choose Keep or Redraw for every pair awaiting an artist verdict",
        )
    pid = state.get("published_pid")
    if not isinstance(pid, str) or not pid:
        raise HTTPException(status_code=409, detail="Session is still being saved")
    workspace_input = state.get("workspace_input") or {}
    voter = getattr(request.state, "user", None)
    voter_sub = voter.sub if voter is not None else "anon"
    try:
        records = [build_feedback(state, sid, index, "up" if verdict == "accept" else "down", voter_sub)
                   for index, verdict in values.items()]
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    _reserve_review_job(sid, sessions)

    def job():
        try:
            lease = runtime.admission_for(state["cfg"].engines).acquire()
            try:
                outcome = runtime.review_for(sessions).apply_verdicts(sid, values)
                published = runtime.publish_review(
                    sid, runtime.review_for(sessions).artifact_dir(sid), outcome,
                    owner_sub=voter_sub, pid=pid, workspace_input=workspace_input)
                if not published.get("published"):
                    raise RuntimeError(published.get("error") or "Could not save review revision")
                # Calibration feedback is non-authoritative telemetry. Never
                # turn a successfully published artist decision into an SSE
                # error merely because its optional analytics write fails.
                try:
                    feedback_store_for(request.app).upsert_many(records)
                except Exception as exc:  # noqa: BLE001 - durable review already committed
                    print(f"[feedback] WARN persistence failed after review publish: {exc}", flush=True)
                return outcome
            finally:
                lease.release()
        finally:
            _release_review_job(sid, sessions)

    return _review_stream(job)
