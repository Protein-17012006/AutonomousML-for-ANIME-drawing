"""FastAPI service for the in-between co-pilot.

POST /session   — multipart: field `keys` (one or more PNG files) + form field
                  `engines` (default "stub").  Returns SSE stream:
                    event: pair    (one per PairResult, in index order)
                    event: result  (final summary + artifact URLs)

GET /session/{sid}/{name} — download a session artifact.
"""
from __future__ import annotations

import io
import itertools
import os
import pathlib
import queue
import tempfile
import threading
import zipfile
from typing import List

import numpy as np
from PIL import Image
from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel

from service.artifacts import build_montage, build_report, build_video, build_pair_frames, save_pair_mid, build_key_frames
from service.demo import build_demo_videos
from service.engines import box_engines, stub_engines
from service.explain import explain_pairs, region_box
from service.runner import run_session, recompute_result
from service.schemas import ErrorEvent, PairEvent, ResultEvent, SessionCfg, sse
from service.session_store import BoundedSessionStore

app = FastAPI(title="In-Between Co-pilot Service")


@app.middleware("http")
async def _no_cache_html(request, call_next):
    """Never let index.html be served stale: a soft reload that reuses a cached index.html
    keeps pointing at a PRE-DEPLOY asset hash, so the user sees an old build (the recurring
    'I deployed but it's still wrong' trap — e.g. an old CSS layout after a fix). The hashed
    JS/CSS bundles are content-addressed/immutable, so they stay cacheable; only the HTML
    entry point is marked no-cache so a plain reload always picks up the latest assets."""
    response = await call_next(request)
    path = request.url.path
    if path == "/" or path.endswith(".html"):
        response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
    return response

# in-process session store: sid -> temp dir path. BOUNDED (audit 2026-07-02): full-res
# numpy keys/frames were retained forever on the long-lived box uvicorn — a slow leak.
# On overflow the oldest session is evicted (temp dir rmtree'd, draw-key state dropped).
# retained run state for the draw-key loop (POST /key): sid -> {keys, eng, cfg, result, rev}
_state: dict[int, dict] = {}
_sessions = BoundedSessionStore(
    cap=int(os.environ.get("COPILOT_MAX_SESSIONS", "8")), state=_state)
_sid_counter = itertools.count(1)

# max key frames a decimated video may yield before we refuse the run (env-tunable).
# A finished cut at stride 2 can be thousands of keys; bound it so a dropped video
# can't pin the box for hours / exhaust memory.
MAX_KEYS = int(os.environ.get("COPILOT_MAX_KEYS", "100"))
# Auto-fit only coarsens the stride up to this factor of the user's stride. A clip that still
# overflows MAX_KEYS at stride*FACTOR is genuinely too long for ONE cut: rather than silently
# decimate it to a sparse, unfaithful set (gaps too large to interpolate → mostly needs-key),
# we fail loudly with the exact stride to use / advice to trim. Keeps "drop a short cut → it
# just runs" while refusing to misrepresent a long montage.
AUTOFIT_MAX_FACTOR = int(os.environ.get("COPILOT_AUTOFIT_MAX_FACTOR", "4"))


def _load_keys(uploads: List[UploadFile]) -> List[np.ndarray]:
    """Read uploaded PNG files (sorted by filename) into numpy HxWx3 arrays."""
    ordered = sorted(uploads, key=lambda u: u.filename or "")
    keys = []
    for u in ordered:
        data = u.file.read()
        img = Image.open(io.BytesIO(data)).convert("RGB")
        keys.append(np.array(img, dtype=np.uint8))
    return keys


def _load_frames_from_video(upload: UploadFile, stride: int) -> "tuple[List[np.ndarray], int, int]":
    """Decode a dropped video and keep every `stride`-th frame as a key. A slightly-long clip
    is AUTO-FIT (the stride is coarsened up to `stride * AUTOFIT_MAX_FACTOR`) so a short cut
    that is a bit over the cap just runs. A clip still over MAX_KEYS at that ceiling is too long
    for one cut → it fails loudly with the exact stride to use (we refuse to silently decimate
    it to a sparse, unfaithful set). Returns `(keys, effective_stride, source_frame_count)`.
    cv2 is imported lazily so the PNG /session path never depends on opencv. Raises
    HTTPException on a non-video, an undecodable clip, a too-long clip, or < 2 keys."""
    ctype = (upload.content_type or "").lower()
    name = (upload.filename or "").lower()
    # The browser sets video/mp4 from File.type, but curl / programmatic clients often send
    # application/octet-stream (or nothing) for an .mp4. Accept those + a known video extension;
    # cv2 is the real arbiter (a non-video that slips past here fails decode -> 422 below). We
    # only early-reject things that are clearly NOT video (e.g. an image/png drop).
    _VIDEO_EXTS = (".mp4", ".mov", ".webm", ".mkv", ".avi", ".m4v")
    looks_like_video = (
        ctype.startswith("video/")
        or ctype in ("application/octet-stream", "")
        or name.endswith(_VIDEO_EXTS)
    )
    if not looks_like_video:
        raise HTTPException(status_code=400, detail=f"expected a video file, got content-type {ctype!r}")
    if stride < 1:
        raise HTTPException(status_code=400, detail="stride must be >= 1")
    try:
        import cv2
    except ImportError:
        raise HTTPException(status_code=500, detail="video decoding unavailable (opencv not installed on the server)")

    data = upload.file.read()
    fd, tmp_path = tempfile.mkstemp(suffix=".mp4", prefix="copilot_video_")
    cap = None
    try:
        with os.fdopen(fd, "wb") as fh:
            fh.write(data)
        cap = cv2.VideoCapture(tmp_path)
        if not cap.isOpened():
            raise HTTPException(status_code=422, detail="couldn't decode this video — is it an H.264 .mp4?")
        src_fps = cap.get(cv2.CAP_PROP_FPS) or 24.0
        max_stride = stride * AUTOFIT_MAX_FACTOR
        keys: List[np.ndarray] = []
        eff_stride = stride          # light auto-coarsening below, capped at max_stride
        idx = 0
        overflow = False             # too long even at the ceiling — keep counting, then error
        while True:
            ret, frame = cap.read()
            if not ret:
                break
            if not overflow and idx % eff_stride == 0:
                rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                keys.append(np.asarray(rgb, dtype=np.uint8))
                if len(keys) > MAX_KEYS:
                    if eff_stride * 2 <= max_stride:
                        # light auto-fit: coarsen one notch. Double the stride and drop every
                        # 2nd kept frame; the survivors stay on the NEW (doubled) stride grid,
                        # so `idx % eff_stride` stays consistent. Memory stays <= MAX_KEYS+1.
                        eff_stride *= 2
                        del keys[1::2]
                    else:
                        # past the auto-fit ceiling: stop collecting, free the buffer, and just
                        # keep counting frames so we can report the exact stride needed.
                        overflow = True
                        keys = []
            idx += 1
    finally:
        if cap is not None:
            cap.release()          # deterministic release even if cv2.read() raised mid-loop
        try:
            os.remove(tmp_path)
        except OSError:
            pass

    if overflow:
        min_stride = max(stride + 1, (idx + MAX_KEYS - 1) // MAX_KEYS)   # ceil(idx / MAX_KEYS)
        secs = idx / src_fps if src_fps else 0
        raise HTTPException(
            status_code=422,
            detail=(f"this clip is {idx} frames (~{secs:.0f}s) — too long to keep as keys. "
                    f"Auto-fit only coarsens up to stride {max_stride} (cap {MAX_KEYS} keys), and "
                    f"sparser keys would have gaps too large to in-between faithfully. Trim it to a "
                    f"single short cut, or raise STRIDE to >= {min_stride}."),
        )
    if len(keys) < 2:
        raise HTTPException(
            status_code=422,
            detail=f"need at least 2 keyframes after decimation; got {len(keys)} (stride={eff_stride}, frames={idx})",
        )
    if eff_stride != stride:
        # surfaced in uvicorn.log — the clip was lightly auto-decimated to fit the MAX_KEYS ceiling
        print(f"[session/video] auto-fit stride {stride} -> {eff_stride} "
              f"({idx} frames -> {len(keys)} keys, cap {MAX_KEYS})", flush=True)
    return keys, eff_stride, idx


def _stream_session(key_arrays: List[np.ndarray], engines: str, fps: int,
                    sampling: dict = None) -> StreamingResponse:
    """Run the co-pilot over `key_arrays` and stream the SSE decision-log + result.
    This is the shared body behind BOTH POST /session and POST /session/video.
    `sampling` (video flow only) surfaces how the clip was decimated, so the UI can show
    "kept K of N frames (every S-th)" and flag a coarse auto-fit."""
    cfg = SessionCfg(engines=engines, fps=fps)
    if engines == "stub":
        eng = stub_engines(cfg)
    elif engines == "box":
        eng = box_engines(cfg)
    else:
        raise HTTPException(status_code=400, detail=f"Unknown engines: {engines!r}")

    sid = next(_sid_counter)
    session_dir = tempfile.mkdtemp(prefix=f"copilot_session_{sid}_")
    _sessions[sid] = session_dir

    def _generate():
        q = queue.Queue()

        def _worker():
            try:
                def on_pair(p):
                    mid_fn = save_pair_mid(p, session_dir)
                    mid_url = f"/session/{sid}/{mid_fn}" if mid_fn else None
                    q.put(("pair", (p, mid_url)))
                result = run_session(key_arrays, eng, on_pair=on_pair)

                vlm_struct_fn = eng.get("vlm_struct_fn")
                if vlm_struct_fn is not None:
                    explanations = explain_pairs(
                        result, vlm_struct_fn=vlm_struct_fn, softness_fn=eng["softness_fn"],
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

                build_montage(result, key_arrays, session_dir, regions=regions or None)
                build_report(result, session_dir)
                build_video(result, session_dir, fps=cfg.fps)
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
                q.put(("result", (result, artifact_urls, explanations, pair_mids, key_urls)))
            except Exception as exc:
                q.put(("error", exc))
            finally:
                q.put(None)

        t = threading.Thread(target=_worker, daemon=True)
        t.start()

        while True:
            item = q.get()
            if item is None:
                break
            kind, payload = item
            if kind == "pair":
                pair_obj, mid_url = payload
                yield sse("pair", PairEvent.from_pair(pair_obj, mid_url=mid_url))
            elif kind == "result":
                result_obj, urls, explanations, pair_mids, key_urls = payload
                yield sse("result", ResultEvent.from_result(result_obj, urls,
                                                            explanations=explanations,
                                                            pair_mids=pair_mids,
                                                            key_urls=key_urls,
                                                            sampling=sampling,
                                                            csq=eng.get("csq_calibrator"),
                                                            qa_degraded=bool(
                                                                eng.get("vlm_status", {}).get("degraded"))))
            elif kind == "error":
                yield sse("error", ErrorEvent(message=str(payload)))
                break

        t.join()

    return StreamingResponse(_generate(), media_type="text/event-stream")


@app.post("/session")
async def post_session(
    keys: List[UploadFile] = File(...),
    engines: str = Form("stub"),
    fps: int = Form(24),
):
    if len(keys) < 2:
        raise HTTPException(status_code=400, detail="Need >= 2 key frames")
    return _stream_session(_load_keys(keys), engines, fps)


@app.post("/session/video")
async def post_session_video(
    video: UploadFile = File(...),
    stride: int = Form(2),
    engines: str = Form("stub"),
    fps: int = Form(24),
):
    """Drop-a-video session: decode the upload, keep every `stride`-th frame as the
    artist's keys, then run the SAME co-pilot session as POST /session."""
    key_arrays, eff_stride, source_frames = _load_frames_from_video(video, stride)
    sampling = {
        "source_frames": source_frames,
        "requested_stride": stride,
        "stride": eff_stride,          # > requested when the clip was lightly auto-fit
        "kept": len(key_arrays),
    }
    return _stream_session(key_arrays, engines, fps, sampling=sampling)


@app.post("/demo")
def post_demo(
    frames: List[UploadFile] = File(...),
    engines: str = Form("stub"),
    fps: int = Form(24),
):
    """Decimate-vs-GT demo: upload a FULL ordered cut -> stride-2 decimate (even=keys,
    odd=hidden GT) -> RIFE the mids -> one side-by-side compare.mp4 (left GOC / right
    RIFE). Synchronous (RIFE-bound); runs in Starlette's threadpool (sync def)."""
    if len(frames) < 3:
        raise HTTPException(status_code=400, detail="Need >= 3 frames for the decimate-vs-GT demo")
    full = _load_keys(frames)

    cfg = SessionCfg(engines=engines, fps=fps)
    if engines == "stub":
        eng = stub_engines(cfg)
    elif engines == "box":
        eng = box_engines(cfg)
    else:
        raise HTTPException(status_code=400, detail=f"Unknown engines: {engines!r}")
    rife = eng.get("rife_engine")
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


class AskReq(BaseModel):
    question: str


@app.post("/session/{sid}/ask")
def post_ask(sid: int, req: AskReq):
    """Grounded Q&A about a finished session (vault 'Chat-First Copilot Surface' §3).
    Answers ONLY from the retained session facts; degrades to a deterministic
    summary when DeepSeek is unconfigured/unreachable — never 500."""
    st = _state.get(sid)
    if st is None:
        raise HTTPException(status_code=404, detail="Unknown session (or no result yet)")
    from service.ask import answer_question
    from service.director_llm import make_ask_fn
    return answer_question(st, req.question, make_ask_fn())


@app.get("/session/{sid}/{name}")
async def get_artifact(sid: int, name: str):
    if sid not in _sessions:
        raise HTTPException(status_code=404, detail="Session not found")
    base = pathlib.Path(_sessions[sid]).resolve()
    # Export bundle: zip the usable artifacts (reconstructed video + in-between
    # frames + montage + report) so the artist takes the result away in one click.
    if name == "bundle.zip":
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
            for f in sorted(base.iterdir()):
                if f.is_file() and f.suffix.lower() in {".mp4", ".png", ".md"}:
                    z.write(f, arcname=f.name)
        buf.seek(0)
        return StreamingResponse(
            buf,
            media_type="application/zip",
            headers={"Content-Disposition": 'attachment; filename="copilot_session.zip"'},
        )
    path = (base / name).resolve()
    if base not in path.parents and path != base:
        raise HTTPException(status_code=400, detail="invalid artifact name")
    if not path.exists():
        raise HTTPException(status_code=404, detail="Artifact not found")
    return FileResponse(str(path))


@app.post("/session/{sid}/key")
async def post_key(sid: int, index: int = Form(...), key: UploadFile = File(...)):
    """Draw-key loop (Tier 2): the artist supplies a drawn breakdown key for gap
    `index` -> TARGETED re-fill. Mini-run the gate->interp->self-QA over just
    [key[index], drawn, key[index+1]] (the two new sub-gaps), splice the 2 sub-pairs
    in place of the gap, re-index the tail, recompute aggregates, rebuild artifacts.
    Returns the full updated pair list + result so the UI replaces its review."""
    st = _state.get(sid)
    if st is None:
        raise HTTPException(status_code=404, detail="Session not found (run a session first)")
    keys, eng, cfg, result = st["keys"], st["eng"], st["cfg"], st["result"]
    if not (0 <= index < len(keys) - 1):
        raise HTTPException(status_code=400, detail=f"gap index {index} out of range")

    data = await key.read()
    m = np.array(Image.open(io.BytesIO(data)).convert("RGB"), dtype=np.uint8)
    a, b = keys[index], keys[index + 1]

    # targeted re-fill: only the two new sub-gaps are gated/interpolated/QA'd
    sub = list(run_session([a, m, b], eng).pairs)   # [a->m, m->b]

    new_keys = keys[:index + 1] + [m] + keys[index + 1:]
    new_pairs: list = []
    for p in result.pairs:
        if p.index < index:
            new_pairs.append(p)
        elif p.index == index:
            sub[0].index = index
            if len(sub) > 1:
                sub[1].index = index + 1
            new_pairs.extend(sub)
        else:
            p.index += 1          # one key inserted -> tail shifts by one
            new_pairs.append(p)
    new_result = recompute_result(new_pairs)

    session_dir = _sessions[sid]

    # explainability + fractional defect boxes (same as the streaming worker)
    vlm_struct_fn = eng.get("vlm_struct_fn")
    explanations = (explain_pairs(new_result, vlm_struct_fn=vlm_struct_fn,
                                  softness_fn=eng["softness_fn"])
                    if vlm_struct_fn is not None else {})
    if explanations:
        H, W = new_keys[0].shape[:2]
        regions = {}
        for i, e in explanations.items():
            pb = region_box(e["region"], W, H)
            regions[i] = pb
            if pb and W and H:
                x0, y0, x1, y1 = pb
                e["box"] = [x0 / W, y0 / H, (x1 - x0) / W, (y1 - y0) / H]
    else:
        regions = {}

    build_montage(new_result, new_keys, session_dir, regions=regions or None)
    build_report(new_result, session_dir)
    build_video(new_result, session_dir, fps=cfg.fps)
    pair_files = build_pair_frames(new_result, session_dir)

    st["keys"], st["result"] = new_keys, new_result
    st["rev"] = st.get("rev", 0) + 1
    bust = f"?r={st['rev']}"     # files are overwritten -> bust the browser cache by URL
    pair_mids = {str(i): f"/session/{sid}/{fn}{bust}" for i, fn in pair_files.items()}
    artifact_urls = {
        "montage": f"/session/{sid}/montage.png{bust}",
        "report":  f"/session/{sid}/report.md{bust}",
        "video":   f"/session/{sid}/reconstructed.mp4{bust}",
    }

    pairs_payload = [
        PairEvent.from_pair(p, mid_url=pair_mids.get(str(p.index))).model_dump()
        for p in new_result.pairs
    ]
    result_payload = ResultEvent.from_result(new_result, artifact_urls,
                                             explanations=explanations,
                                             pair_mids=pair_mids,
                                             csq=eng.get("csq_calibrator")).model_dump()
    return {"pairs": pairs_payload, "result": result_payload}


# --- static web UI: mounted LAST so the API routes above take precedence ---
from fastapi.staticfiles import StaticFiles  # noqa: E402

# Default = the vanilla web/ (always present → tests + dev fallback). Set
# COPILOT_WEB_DIR (relative to the repo root, or absolute) to serve the built
# React SPA instead — the box launches with COPILOT_WEB_DIR=dist.
_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_WEB_DIR = os.environ.get("COPILOT_WEB_DIR") or "web"
if not os.path.isabs(_WEB_DIR):
    _WEB_DIR = os.path.join(_ROOT, _WEB_DIR)
if os.path.isdir(_WEB_DIR):
    app.mount("/", StaticFiles(directory=_WEB_DIR, html=True), name="web")
