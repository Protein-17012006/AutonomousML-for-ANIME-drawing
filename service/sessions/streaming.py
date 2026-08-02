"""SSE inbound adapter for the run-session application use case."""
from __future__ import annotations

import json
import queue
import threading
from dataclasses import dataclass
from typing import Callable

import numpy as np
from fastapi import HTTPException
from fastapi.responses import StreamingResponse

from service.core.config import sse_keepalive_seconds
from service.core.errors import RuntimeBusy, UnknownEngine
from service.core.http import model_or_422
from service.sessions.repository import SessionRepository
from service.sessions.schemas import ErrorEvent, PairEvent, ResultEvent, SessionCfg, sse
from service.sessions.service import RunSession


KEEPALIVE_SECS = sse_keepalive_seconds()
EVENT_QUEUE_CAP = 256


@dataclass(frozen=True)
class SessionStreamPorts:
    """Concrete operations supplied once by the application composition root."""

    resolve_engine: Callable
    admission_for: Callable
    workflow_for: Callable[[SessionRepository], RunSession]


class _ClientDisconnected(Exception):
    pass

def _drain_events(q: "queue.Queue", keepalive: "float | None" = None):
    """Drain worker events, emitting transport keepalives while it is idle."""
    interval = KEEPALIVE_SECS if keepalive is None else keepalive
    while True:
        try:
            item = q.get(timeout=interval)
        except queue.Empty:
            yield "ping", None
            continue
        if item is None:
            return
        yield item


def stream_session(key_arrays: list[np.ndarray], engines: str, *,
                   ports: SessionStreamPorts,
                   repository: SessionRepository,
                   interpolator: str = "rife",
                   cadence_fps: int = 12,
                   smoothness: int = 2, sampling: dict = None, show: str = None,
                   owner_sub: str | None = None,
                   history_pid: str | None = None,
                   workspace_input: dict | None = None,
                   source_video: bytes | None = None,
                   active_workspace=None,
                   gt_frames: list | None = None) -> StreamingResponse:
    """Start one run and adapt its pair/result callbacks to an SSE response."""
    cfg = model_or_422(
        SessionCfg,
        engines=engines, cadence_fps=cadence_fps,
        smoothness=smoothness, show=show, interpolator=interpolator,
    )
    try:
        admission = ports.admission_for(engines)
    except UnknownEngine as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    def generate():
        events = queue.Queue(maxsize=EVENT_QUEUE_CAP)
        disconnected = threading.Event()
        use_case = ports.workflow_for(repository)
        thread = None

        # Admission happens before both CUDA initialization and worker creation.
        # The synchronous response iterator runs in Starlette's thread pool, so a
        # bounded wait does not block the asyncio event loop.
        try:
            lease = admission.acquire()
        except RuntimeBusy as exc:
            yield sse("error", ErrorEvent(message=str(exc)))
            return

        sid = None
        active_manifest = None
        try:
            eng = ports.resolve_engine(
                engines, interpolator=cfg.interpolator
            )
            sid, session_dir = repository.create("copilot_session", pin=True)
            if owner_sub:
                repository.set_owner(sid, owner_sub)
                if active_workspace is not None:
                    active_manifest = active_workspace.create_or_get(
                        owner_sub,
                        history_pid=history_pid,
                        initial_snapshot={"upload": workspace_input or {}},
                    )
                    active_workspace.stage_input_arrays(owner_sub, key_arrays)
                    if source_video is not None:
                        active_workspace.stage_input_video(owner_sub, source_video)
                    active_workspace.append_event(owner_sub, "workspace", {
                        "workspace_id": active_manifest.workspace_id,
                        "revision": active_manifest.revision,
                    })
        except Exception as exc:
            if sid is not None:
                repository.unpin(sid)
            lease.release()
            yield sse("error", ErrorEvent(message=str(exc)))
            return

        def put_event(item):
            # Bounded backpressure without trapping a worker forever after the
            # client disconnects while the queue is full.
            while not disconnected.is_set():
                try:
                    events.put(item, timeout=0.25)
                    return True
                except queue.Full:
                    continue
            return False

        def _journal(kind, payload):
            if active_manifest is None:
                return
            if kind == "pair":
                pair, mid_url = payload
                body = PairEvent.from_pair(pair, mid_url=mid_url).model_dump()
            elif kind == "result":
                outcome = payload
                body = ResultEvent.from_result(
                    outcome.result, outcome.artifact_urls,
                    sid=outcome.sid,
                    explanations=outcome.explanations, pair_mids=outcome.pair_mids,
                    key_urls=outcome.key_urls,
                        pair_keys=getattr(outcome, 'pair_keys', {}) or {}, sampling=outcome.sampling,
                    csq=outcome.csq, qa_degraded=outcome.qa_degraded,
                ).model_dump()
            elif kind == "publish":
                body = dict(payload)
            else:
                body = {"message": str(payload)}
            active_workspace.append_event(owner_sub, kind, body)

        def emit(kind, payload):
            # Persist before delivery. A browser disconnect only detaches this
            # response; it no longer cancels an authenticated active job.
            _journal(kind, payload)
            if disconnected.is_set() and active_manifest is not None:
                return
            if disconnected.is_set():
                raise _ClientDisconnected()
            if not put_event((kind, payload)):
                if active_manifest is None:
                    raise _ClientDisconnected()

        def worker():
            try:
                outcome = use_case.execute(
                    sid, session_dir, key_arrays, eng, cfg, sampling=sampling,
                    gt_frames=gt_frames,
                    emit_pair=lambda pair, url: emit("pair", (pair, url)),
                )
                emit("result", outcome)
                if active_manifest is not None:
                    active_workspace.stage_generated(owner_sub, session_dir)
                    active_workspace.set_state(
                        owner_sub, "ready", snapshot={
                            "upload": workspace_input or {},
                            "pairs": [event.data for event in active_workspace.get(owner_sub).events if event.name == "pair"],
                            "result": ResultEvent.from_result(
                                outcome.result, outcome.artifact_urls,
                                sid=outcome.sid,
                                explanations=outcome.explanations, pair_mids=outcome.pair_mids,
                                key_urls=outcome.key_urls,
                        pair_keys=getattr(outcome, 'pair_keys', {}) or {}, sampling=outcome.sampling,
                                csq=outcome.csq, qa_degraded=outcome.qa_degraded,
                            ).model_dump(),
                        })
                published = use_case.publish(
                    sid,
                    session_dir,
                    outcome,
                    history_pid=history_pid,
                    workspace_input=workspace_input,
                )
                if published.get("published"):
                    published_pid = published.get("pid")
                    state = repository.state_for(sid)
                    if state is not None and isinstance(published_pid, str):
                        repository.save_state(sid, {
                            **state,
                            "published_pid": published_pid,
                            "workspace_input": workspace_input or {},
                        })
                    if active_manifest is not None:
                        active_workspace.set_state(owner_sub, "published", published_pid=published_pid)
                    emit("publish", {"pid": published_pid, "published": True})
                    print(
                        f"[publisher] published {len(published['s3_keys'])} objects",
                        flush=True,
                    )
                elif active_manifest is not None:
                    active_workspace.set_state(owner_sub, "publish_pending")
                    error = published.get("error")
                    emit("publish", {
                        "published": False,
                        "error": error if isinstance(error, str) else "Durable publication needs a retry.",
                    })
            except _ClientDisconnected:
                pass
            except Exception as exc:
                if active_manifest is not None:
                    active_workspace.set_state(owner_sub, "failed")
                    _journal("error", exc)
                elif not disconnected.is_set():
                    emit("error", exc)
            finally:
                try:
                    repository.unpin(sid)
                finally:
                    lease.release()
                    put_event(None)

        thread = threading.Thread(
            target=worker, name=f"copilot-session-{sid}", daemon=True)
        thread.start()

        try:
            for kind, payload in _drain_events(events):
                if kind == "ping":
                    yield ": ping\n\n"
                elif kind == "pair":
                    pair, mid_url = payload
                    yield sse("pair", PairEvent.from_pair(pair, mid_url=mid_url))
                elif kind == "result":
                    outcome = payload
                    yield sse("result", ResultEvent.from_result(
                        outcome.result,
                        outcome.artifact_urls,
                        sid=outcome.sid,
                        explanations=outcome.explanations,
                        pair_mids=outcome.pair_mids,
                        key_urls=outcome.key_urls,
                        pair_keys=getattr(outcome, 'pair_keys', {}) or {},
                        sampling=outcome.sampling,
                        csq=outcome.csq,
                        qa_degraded=outcome.qa_degraded,
                    ))
                elif kind == "error":
                    yield sse("error", ErrorEvent(message=str(payload)))
                    break
                elif kind == "publish":
                    yield f"event: publish\ndata: {json.dumps(payload)}\n\n"
        finally:
            disconnected.set()
            # The worker retains the repository pin + runtime lease until it
            # actually exits; a disconnected client cannot trigger early eviction
            # or allow overlapping CUDA inference.
            if thread is not None:
                thread.join(timeout=0.1)

    return StreamingResponse(generate(), media_type="text/event-stream")
