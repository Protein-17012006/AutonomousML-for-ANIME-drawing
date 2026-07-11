"""SSE inbound adapter for the run-session application use case."""
from __future__ import annotations

import queue
import threading
from typing import List

import numpy as np
from fastapi import HTTPException
from fastapi.responses import StreamingResponse
from pydantic import ValidationError

from service.core.config import sse_keepalive_seconds
from service.core.errors import UnknownEngine
from service.infrastructure.engines import resolve
from service.infrastructure.publisher import publish_session
from service.media.annotate import annotate_explained_pairs
from service.media.artifacts import (
    _assemble_frames, build_key_frames, build_montage, build_pair_frames,
    build_report, build_video, save_pair_mid,
)
from service.media.explain import explain_pairs, region_box
from service.sessions.repository import SessionRepository
from service.sessions.runner import run_session
from service.sessions.schemas import ErrorEvent, PairEvent, ResultEvent, SessionCfg, sse
from service.sessions.service import RunSession, SessionWorkflowAdapters
from service.sessions.dependencies import default_session_repository


KEEPALIVE_SECS = sse_keepalive_seconds()


def _session_cfg_or_422(**kwargs) -> SessionCfg:
    """Map request validation failures to the HTTP transport at the API edge."""
    try:
        return SessionCfg(**kwargs)
    except ValidationError as exc:
        detail = "; ".join(error["msg"] for error in exc.errors()) or str(exc)
        raise HTTPException(status_code=422, detail=detail) from exc


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


def _workflow(repository: SessionRepository) -> RunSession:
    """Compose the application use case with concrete outbound adapters."""
    return RunSession(repository, SessionWorkflowAdapters(
        run_pipeline=run_session,
        save_pair_mid=save_pair_mid,
        explain_pairs=explain_pairs,
        region_box=region_box,
        annotate_pairs=annotate_explained_pairs,
        assemble_frames=_assemble_frames,
        build_montage=build_montage,
        build_report=build_report,
        build_video=build_video,
        build_pair_frames=build_pair_frames,
        build_key_frames=build_key_frames,
        publish_session=publish_session,
    ))


def stream_session(key_arrays: List[np.ndarray], engines: str, *, cadence_fps: int = 12,
                   smoothness: int = 2, sampling: dict = None, show: str = None,
                   repository: SessionRepository | None = None) -> StreamingResponse:
    """Start one run and adapt its pair/result callbacks to an SSE response."""
    cfg = _session_cfg_or_422(
        engines=engines, cadence_fps=cadence_fps,
        smoothness=smoothness, show=show,
    )
    try:
        eng = resolve(engines, cfg)
    except UnknownEngine as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    repository = repository or default_session_repository
    sid, session_dir = repository.create("copilot_session")

    def generate():
        events = queue.Queue()
        use_case = _workflow(repository)

        def worker():
            try:
                outcome = use_case.execute(
                    sid, session_dir, key_arrays, eng, cfg, sampling=sampling,
                    emit_pair=lambda pair, url: events.put(("pair", (pair, url))),
                )
                events.put(("result", outcome))
                published = use_case.publish(sid, session_dir, outcome.result)
                if published.get("published"):
                    print(
                        f"[publisher] session {sid} published pid={published['pid']} "
                        f"({len(published['s3_keys'])} objects)",
                        flush=True,
                    )
            except Exception as exc:
                events.put(("error", exc))
            finally:
                events.put(None)

        thread = threading.Thread(target=worker, daemon=True)
        thread.start()

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
                    csq=eng.csq_calibrator,
                    qa_degraded=bool(eng.vlm_status.get("degraded")),
                ))
            elif kind == "error":
                yield sse("error", ErrorEvent(message=str(payload)))
                break

        thread.join()

    return StreamingResponse(generate(), media_type="text/event-stream")
