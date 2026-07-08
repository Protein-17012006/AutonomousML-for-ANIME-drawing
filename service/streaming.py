"""Run the co-pilot over key arrays and stream the SSE decision-log — the shared
body behind POST /session, /session/video and /session/planted."""
from __future__ import annotations

import os
import queue
import tempfile
import threading
from typing import List

import numpy as np
from fastapi import HTTPException
from fastapi.responses import StreamingResponse
from pydantic import ValidationError

from service.annotate import annotate_explained_pairs
from service.artifacts import (build_montage, build_report, build_video, build_pair_frames,
                               save_pair_mid, build_key_frames, _assemble_frames)
from service.engines import resolve
from service.explain import explain_pairs, region_box
from service.publisher import publish_session
from service.runner import run_session
from service.schemas import ErrorEvent, PairEvent, ResultEvent, SessionCfg, sse
from service.state import _sessions, _sid_counter, _state

# SSE keepalive: CloudFront's origin read timeout (60s) is an IDLE timeout — it only
# fires when no bytes flow. A slow first pair (RIFE+VLM warm-up) can exceed it, so the
# drain loop emits an SSE *comment* line every KEEPALIVE_SECS of queue silence.
# Comments (`: ...`) are ignored by every SSE parser, including our frontend's.
KEEPALIVE_SECS = float(os.environ.get("COPILOT_SSE_KEEPALIVE", "15"))


def _session_cfg_or_422(**kwargs) -> SessionCfg:
    """Build a `SessionCfg` from request-derived fields (cadence/smoothness/...),
    turning an invalid `smoothness` (not in {1,2,4}) or a gated `smoothness=4`
    (COPILOT_SMOOTHNESS_X4 unset) into an actionable HTTP 422 instead of letting
    pydantic's `ValidationError` bubble up to FastAPI's default handler as a bare 500."""
    try:
        return SessionCfg(**kwargs)
    except ValidationError as exc:
        detail = "; ".join(e["msg"] for e in exc.errors()) or str(exc)
        raise HTTPException(status_code=422, detail=detail) from exc


def _drain_events(q: "queue.Queue", keepalive: "float | None" = None):
    """Yield (kind, payload) items from `q` until the None sentinel; on `keepalive`
    seconds of idleness yield ("ping", None) instead of blocking forever."""
    ka = KEEPALIVE_SECS if keepalive is None else keepalive
    while True:
        try:
            item = q.get(timeout=ka)
        except queue.Empty:
            yield ("ping", None)
            continue
        if item is None:
            return
        yield item


def stream_session(key_arrays: List[np.ndarray], engines: str, *, cadence_fps: int = 12,
                    smoothness: int = 2, sampling: dict = None,
                    eng_override: dict = None) -> StreamingResponse:
    """Run the co-pilot over `key_arrays` and stream the SSE decision-log + result.
    This is the shared body behind POST /session, /session/video and /session/planted.
    `cadence_fps`/`smoothness` (Smoothness Control) build `SessionCfg`, whose `fps`
    derives as `cadence_fps * smoothness` — the reconstructed-video playback rate.
    `sampling` (video flow only) surfaces how the clip was decimated, so the UI can show
    "kept K of N frames (every S-th)" and flag a coarse auto-fit; it also gains the
    cadence/smoothness/output_fps/duration badge fields once the result is built.
    `eng_override` (planted-demo flow only) replaces named engine callables after the build."""
    cfg = _session_cfg_or_422(engines=engines, cadence_fps=cadence_fps, smoothness=smoothness)
    eng = resolve(engines, cfg)
    if eng_override:
        eng = eng.override(**eng_override)
    # raw 1-mid RIFE, present in both stub_engines/box_engines dicts — only exercised by
    # build_video's smoothness=4 re-interpolation branch (harmless to pass otherwise).
    mid_engine = eng.rife_engine

    sid = next(_sid_counter)
    session_dir = tempfile.mkdtemp(prefix=f"copilot_session_{sid}_")
    _sessions[sid] = session_dir

    def _generate():
        q = queue.Queue()

        def _worker():
            nonlocal sampling
            try:
                def on_pair(p):
                    mid_fn = save_pair_mid(p, session_dir)
                    mid_url = f"/session/{sid}/{mid_fn}" if mid_fn else None
                    q.put(("pair", (p, mid_url)))
                result = run_session(key_arrays, eng, on_pair=on_pair)

                vlm_struct_fn = eng.vlm_struct_fn
                if vlm_struct_fn is not None:
                    explanations = explain_pairs(
                        result, vlm_struct_fn=vlm_struct_fn, softness_fn=eng.softness_fn,
                    )
                else:
                    explanations = {}

                if explanations and len(key_arrays) > 0:
                    sample = key_arrays[0]
                    H, W = sample.shape[:2]
                    regions = {}
                    for i, e in explanations.items():
                        pb = region_box(e["region"], W, H)
                        regions[i] = pb
                        if pb and W and H:
                            x0, y0, x1, y1 = pb
                            e["box"] = [x0 / W, y0 / H, (x1 - x0) / W, (y1 - y0) / H]
                else:
                    regions = {}

                for i, fn in annotate_explained_pairs(result, explanations, session_dir).items():
                    explanations[i]["annotated_url"] = f"/session/{sid}/{fn}"

                # Smoothness Control badge: cadence/smoothness/output_fps + the reconstructed
                # clip's duration (reuse Task 2's frame assembler — don't invent a new counter).
                # Computed here (before build_report) so the headline badge and the SSE
                # `sampling` payload below share the same value.
                # M2 fix: assemble ONCE and reuse for both the duration badge and build_video —
                # at smoothness=4 `_assemble_frames` re-runs the (GPU) RIFE mid_engine per pair,
                # so assembling twice per session doubled that work for nothing.
                assembled = _assemble_frames(result, factor=cfg.smoothness, mid_engine=mid_engine)
                duration = len(assembled) / cfg.fps

                build_montage(result, key_arrays, session_dir, regions=regions or None)
                build_report(result, session_dir, cadence_fps=cfg.cadence_fps, smoothness=cfg.smoothness,
                            output_fps=cfg.fps, duration=duration)
                build_video(result, session_dir, fps=cfg.fps, factor=cfg.smoothness, mid_engine=mid_engine,
                           frames=assembled)
                pair_files = build_pair_frames(result, session_dir)
                # Serve the key frames too — the drop-a-video flow has no client-side key
                # images (they're decoded server-side), so without these the review A/B cells
                # render black. The PNG-upload UI ignores these (it has client object URLs).
                key_files = build_key_frames(key_arrays, session_dir)
                _state[sid] = {"keys": key_arrays, "eng": eng, "cfg": cfg, "result": result, "rev": 0}
                pair_mids = {str(i): f"/session/{sid}/{fn}" for i, fn in pair_files.items()}
                key_urls = {str(i): f"/session/{sid}/{fn}" for i, fn in key_files.items()}
                artifact_urls = {
                    "montage": f"/session/{sid}/montage.png",
                    "report":  f"/session/{sid}/report.md",
                    "video":   f"/session/{sid}/reconstructed.mp4",
                }
                # duration was already computed above (shared with the build_report badge call)
                if sampling is None:
                    sampling = {}
                sampling.update({
                    "cadence_fps": cfg.cadence_fps,
                    "smoothness": cfg.smoothness,
                    "output_fps": cfg.fps,
                    "duration": round(duration, 3),
                })
                q.put(("result", (result, artifact_urls, explanations, pair_mids, key_urls)))
                # AWS persistence (design §2 Luồng 3): after the client already has the
                # result event. Env-gated + fail-soft — a dead AWS never hurts the session.
                pub = publish_session(sid, session_dir, result)
                if pub.get("published"):
                    print(f"[publisher] session {sid} published pid={pub['pid']} "
                          f"({len(pub['s3_keys'])} objects)", flush=True)
            except Exception as exc:
                q.put(("error", exc))
            finally:
                q.put(None)

        t = threading.Thread(target=_worker, daemon=True)
        t.start()

        for kind, payload in _drain_events(q):
            if kind == "ping":
                yield ": ping\n\n"
            elif kind == "pair":
                pair_obj, mid_url = payload
                yield sse("pair", PairEvent.from_pair(pair_obj, mid_url=mid_url))
            elif kind == "result":
                result_obj, urls, explanations, pair_mids, key_urls = payload
                yield sse("result", ResultEvent.from_result(result_obj, urls,
                                                            explanations=explanations,
                                                            pair_mids=pair_mids,
                                                            key_urls=key_urls,
                                                            sampling=sampling,
                                                            csq=eng.csq_calibrator,
                                                            qa_degraded=bool(
                                                                eng.vlm_status.get("degraded"))))
            elif kind == "error":
                yield sse("error", ErrorEvent(message=str(payload)))
                break

        t.join()

    return StreamingResponse(_generate(), media_type="text/event-stream")
