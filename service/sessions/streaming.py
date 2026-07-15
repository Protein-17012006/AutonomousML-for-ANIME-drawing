"""SSE inbound adapter for the run-session application use case."""
from __future__ import annotations

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
                   cadence_fps: int = 12,
                   smoothness: int = 2, sampling: dict = None, show: str = None,
                   owner_sub: str | None = None) -> StreamingResponse:
    """Start one run and adapt its pair/result callbacks to an SSE response."""
    cfg = model_or_422(
        SessionCfg,
        engines=engines, cadence_fps=cadence_fps,
        smoothness=smoothness, show=show,
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
        try:
            eng = ports.resolve_engine(engines)
            sid, session_dir = repository.create("copilot_session", pin=True)
            if owner_sub:
                repository.set_owner(sid, owner_sub)
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

        def emit(kind, payload):
            if disconnected.is_set():
                raise _ClientDisconnected()
            if not put_event((kind, payload)):
                raise _ClientDisconnected()

        def worker():
            try:
                outcome = use_case.execute(
                    sid, session_dir, key_arrays, eng, cfg, sampling=sampling,
                    emit_pair=lambda pair, url: emit("pair", (pair, url)),
                )
                emit("result", outcome)
                published = use_case.publish(sid, session_dir, outcome.result)
                if published.get("published"):
                    print(
                        f"[publisher] published {len(published['s3_keys'])} objects",
                        flush=True,
                    )
            except _ClientDisconnected:
                pass
            except Exception as exc:
                if not disconnected.is_set():
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
                        explanations=outcome.explanations,
                        pair_mids=outcome.pair_mids,
                        key_urls=outcome.key_urls,
                        sampling=outcome.sampling,
                        csq=outcome.csq,
                        qa_degraded=outcome.qa_degraded,
                    ))
                elif kind == "error":
                    yield sse("error", ErrorEvent(message=str(payload)))
                    break
        finally:
            disconnected.set()
            # The worker retains the repository pin + runtime lease until it
            # actually exits; a disconnected client cannot trigger early eviction
            # or allow overlapping CUDA inference.
            if thread is not None:
                thread.join(timeout=0.1)

    return StreamingResponse(generate(), media_type="text/event-stream")
