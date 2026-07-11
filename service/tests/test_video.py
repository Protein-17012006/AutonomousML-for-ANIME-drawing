"""Tests for service.app._load_frames_from_video (video decode + decimate + guards)."""
import io
import os
import tempfile

import numpy as np
import pytest

pytest.importorskip("fastapi")   # box cogvideo-venv only; skip (not error) off-box
from starlette.datastructures import Headers, UploadFile

import service.media.ingest as ingest_mod
from service.app import app
from service.media.ingest import _load_frames_from_video
from fastapi import HTTPException
from fastapi.testclient import TestClient


def _mp4_bytes(n: int, size: int = 16) -> bytes:
    """A tiny H.264 mp4 of n solid-colour frames (same imageio backend the service
    already uses to ENCODE output, so the env that runs the service can decode it)."""
    import imageio.v2 as imageio
    frames = [np.full((size, size, 3), (i * 12) % 256, np.uint8) for i in range(n)]
    fd, path = tempfile.mkstemp(suffix=".mp4")
    os.close(fd)
    try:
        imageio.mimwrite(path, frames, fps=24, codec="libx264",
                         pixelformat="yuv420p", macro_block_size=None)
        with open(path, "rb") as fh:
            return fh.read()
    finally:
        os.remove(path)


def _upload(data: bytes, name: str = "cut.mp4", ctype: str = "video/mp4") -> UploadFile:
    return UploadFile(file=io.BytesIO(data), filename=name,
                      headers=Headers({"content-type": ctype}))


def _mp4_bytes_near_static(n: int, size: int = 16) -> bytes:
    """Like `_mp4_bytes` but with a much SMALLER colour step, so consecutive KEPT keys
    stay under stub_engines' gap gate (tau_gate=0.017, gap = mean|diff|/100) and the pair
    actually gets FILLED instead of gated to needs_key. `_mp4_bytes`'s step of 12/frame
    (used by the decode/decimate tests above, which don't care about fill vs needs_key)
    is far too large a jump for that — this fixture is for tests that need a non-empty
    reconstructed clip (e.g. the cadence-badge duration)."""
    import imageio.v2 as imageio
    frames = [np.full((size, size, 3), (i // 2) % 256, np.uint8) for i in range(n)]
    fd, path = tempfile.mkstemp(suffix=".mp4")
    os.close(fd)
    try:
        imageio.mimwrite(path, frames, fps=24, codec="libx264",
                         pixelformat="yuv420p", macro_block_size=None)
        with open(path, "rb") as fh:
            return fh.read()
    finally:
        os.remove(path)


def test_decode_decimates_stride_2():
    keys, eff, total, src_fps = _load_frames_from_video(_upload(_mp4_bytes(6)), stride=2)
    assert len(keys) == 3                          # frames[0::2] of 6 == 3
    assert eff == 2 and total == 6                  # no auto-fit needed
    assert keys[0].ndim == 3 and keys[0].shape[2] == 3
    assert keys[0].dtype == np.uint8


def test_decode_stride_1_keeps_all():
    keys, eff, total, src_fps = _load_frames_from_video(_upload(_mp4_bytes(5)), stride=1)
    assert len(keys) == 5 and eff == 1 and total == 5


def test_returns_source_fps():
    # cadence derivation (Smoothness Control) needs the clip's native fps alongside the
    # effective stride; _mp4_bytes always encodes at fps=24 (see the helper above).
    keys, eff, total, src_fps = _load_frames_from_video(_upload(_mp4_bytes(6)), stride=2)
    assert src_fps == 24.0
    assert round(src_fps / eff) == 12   # cadence at stride 2


def test_rejects_non_video_content_type():
    with pytest.raises(HTTPException) as ei:
        _load_frames_from_video(_upload(_mp4_bytes(6), name="x.png", ctype="image/png"), stride=2)
    assert ei.value.status_code == 400


def test_accepts_octet_stream_content_type():
    # curl / programmatic clients send application/octet-stream for an .mp4; the helper must
    # accept it (cv2 is the real validator), not reject at the door. Regression for the box smoke.
    keys, _eff, _total, _src_fps = _load_frames_from_video(
        _upload(_mp4_bytes(6), name="cut.mp4", ctype="application/octet-stream"), stride=2)
    assert len(keys) == 3


def test_rejects_too_few_keys():
    # 3 frames, stride 3 -> frames[0::3] == 1 key -> below the 2-key minimum
    with pytest.raises(HTTPException) as ei:
        _load_frames_from_video(_upload(_mp4_bytes(3)), stride=3)
    assert ei.value.status_code == 422


def test_long_video_autofits_to_cap(monkeypatch):
    # A slightly-long clip (within the stride*FACTOR ceiling) auto-coarsens the stride so it
    # fits (<= MAX_KEYS) and still runs (>= 2 keys), instead of failing.
    monkeypatch.setattr(ingest_mod, "MAX_KEYS", 3)
    keys, eff, total, src_fps = _load_frames_from_video(_upload(_mp4_bytes(10)), stride=1)  # 10 keys @ stride 1
    assert 2 <= len(keys) <= 3
    assert eff > 1 and eff <= 1 * ingest_mod.AUTOFIT_MAX_FACTOR   # auto-fit happened, within the cap
    assert total == 10
    assert keys[0].ndim == 3 and keys[0].shape[2] == 3


def test_too_long_clip_errors_actionably(monkeypatch):
    # Past the auto-fit ceiling (stride * AUTOFIT_MAX_FACTOR) the clip is too long for one cut:
    # fail loudly with the stride to use, rather than silently decimate to an unfaithful set.
    monkeypatch.setattr(ingest_mod, "MAX_KEYS", 3)
    monkeypatch.setattr(ingest_mod, "AUTOFIT_MAX_FACTOR", 4)
    with pytest.raises(HTTPException) as ei:
        _load_frames_from_video(_upload(_mp4_bytes(20)), stride=1)  # 20 frames > 3 keys even @ stride 4
    assert ei.value.status_code == 422
    assert "STRIDE" in ei.value.detail and "trim" in ei.value.detail.lower()


def test_session_video_streams_pairs_then_result():
    c = TestClient(app)
    r = c.post(
        "/session/video",
        files=[("video", ("cut.mp4", io.BytesIO(_mp4_bytes(6)), "video/mp4"))],
        data={"engines": "stub", "stride": "2"},
    )
    assert r.status_code == 200
    assert "text/event-stream" in r.headers["content-type"]
    body = r.text
    assert "event: pair" in body
    assert body.count("event: result") == 1
    assert body.index("event: pair") < body.index("event: result")


def test_session_video_rejects_non_video():
    c = TestClient(app)
    # send a PNG under the `video` field
    png = io.BytesIO()
    from PIL import Image
    Image.fromarray(np.zeros((8, 8, 3), np.uint8)).save(png, "PNG")
    png.seek(0)
    r = c.post("/session/video",
               files=[("video", ("x.png", png, "image/png"))],
               data={"engines": "stub", "stride": "2"})
    assert r.status_code == 400


def test_session_video_autofits_long_clip(monkeypatch):
    # Regression for the dropped-video bug: a clip that decimates to more than MAX_KEYS now
    # STREAMS a session (auto-fit coarsens the stride) instead of failing with 422.
    monkeypatch.setattr(ingest_mod, "MAX_KEYS", 3)
    c = TestClient(app)
    r = c.post("/session/video",
               files=[("video", ("cut.mp4", io.BytesIO(_mp4_bytes(10)), "video/mp4"))],
               data={"engines": "stub", "stride": "1"})
    assert r.status_code == 200
    assert "text/event-stream" in r.headers["content-type"]
    assert "event: result" in r.text


def test_build_key_frames_writes_pngs(tmp_path):
    from service.media.artifacts import build_key_frames
    keys = [np.full((8, 8, 3), (i * 30) % 256, np.uint8) for i in range(3)]
    m = build_key_frames(keys, str(tmp_path))
    assert set(m) == {0, 1, 2}
    for i in range(3):
        assert (tmp_path / f"key_{i}.png").exists()


def test_session_video_result_carries_key_urls():
    # Regression for the black A/B cells: the drop-a-video flow has no client-side key
    # images (keys are decoded server-side), so the result MUST serve key_urls
    # (key index -> /session/{sid}/key_i.png) for the review triptych to render them.
    import json
    c = TestClient(app)
    r = c.post("/session/video",
               files=[("video", ("cut.mp4", io.BytesIO(_mp4_bytes(6)), "video/mp4"))],
               data={"engines": "stub", "stride": "2"})
    assert r.status_code == 200
    block = next(b for b in r.text.split("\n\n") if "event: result" in b)
    data = next(l for l in block.split("\n") if l.startswith("data:"))[len("data:"):].strip()
    key_urls = json.loads(data).get("key_urls") or {}
    assert len(key_urls) == 3                       # 6 frames, stride 2 -> 3 keys
    assert key_urls["0"].startswith("/session/") and key_urls["0"].endswith("key_0.png")


def test_session_video_too_long_errors(monkeypatch):
    # A clip past the auto-fit ceiling returns an actionable 422 (the FE surfaces detail as a
    # banner) instead of streaming a silently-unfaithful sparse session.
    monkeypatch.setattr(ingest_mod, "MAX_KEYS", 3)
    monkeypatch.setattr(ingest_mod, "AUTOFIT_MAX_FACTOR", 4)
    c = TestClient(app)
    r = c.post("/session/video",
               files=[("video", ("cut.mp4", io.BytesIO(_mp4_bytes(20)), "video/mp4"))],
               data={"engines": "stub", "stride": "1"})
    assert r.status_code == 422
    assert "STRIDE" in r.json()["detail"]


def test_session_video_reports_sampling():
    # The result carries a `sampling` summary so the UI can show how the clip was decimated.
    import json
    c = TestClient(app)
    r = c.post("/session/video",
               files=[("video", ("cut.mp4", io.BytesIO(_mp4_bytes(6)), "video/mp4"))],
               data={"engines": "stub", "stride": "2"})
    assert r.status_code == 200
    block = next(b for b in r.text.split("\n\n") if "event: result" in b)
    data = next(l for l in block.split("\n") if l.startswith("data:"))[len("data:"):].strip()
    s = json.loads(data).get("sampling")
    assert s and s["source_frames"] == 6 and s["kept"] == 3
    assert s["requested_stride"] == 2 and s["stride"] == 2


def test_video_session_reports_cadence_badge():
    # Smoothness Control (Task 6): sampling gains {cadence_fps, smoothness, output_fps,
    # duration}. cadence is DERIVED from the clip's own fps/stride (24fps / stride 2 = 12),
    # not the (ignored) form default, and output_fps = cadence_fps * smoothness. Uses the
    # near-static fixture so the pairs actually FILL (duration > 0), not gate to needs_key.
    import json
    c = TestClient(app)
    r = c.post("/session/video",
               files=[("video", ("c.mp4", io.BytesIO(_mp4_bytes_near_static(6)), "video/mp4"))],
               data={"engines": "stub", "stride": "2", "smoothness": "2"})
    assert r.status_code == 200
    block = next(b for b in r.text.split("\n\n") if "event: result" in b)
    data = next(l for l in block.split("\n") if l.startswith("data:"))[len("data:"):].strip()
    result = json.loads(data)
    s = result["sampling"]
    assert s["cadence_fps"] == 12 and s["smoothness"] == 2 and s["output_fps"] == 24
    assert s["duration"] > 0


def test_qa_invariant_across_smoothness(monkeypatch):
    """Pins the feature's core safety claim (final-review M1): smoothness is
    DISPLAY-ONLY (fps/duration/frame-count expansion) — QA runs on the interpolated
    x2 triplet via `run_session(key_arrays, eng, ...)`, which never sees `cfg`/smoothness
    at all. So for a FIXED set of keys, the QA outcome (autopass count, flagged/abstained
    sets, and the per-pair action/qa verdicts) must be IDENTICAL whether smoothness is
    1, 2, or 4 (x4 unblocked via the env flag) — only output_fps/duration may differ."""
    import json
    import re

    monkeypatch.setenv("COPILOT_SMOOTHNESS_X4", "1")   # unblock the x4 run too
    c = TestClient(app)
    video_bytes = _mp4_bytes_near_static(6)   # near-static so pairs actually FILL

    def _run(smoothness: int):
        r = c.post(
            "/session/video",
            files=[("video", ("c.mp4", io.BytesIO(video_bytes), "video/mp4"))],
            data={"engines": "stub", "stride": "2", "smoothness": str(smoothness)},
        )
        assert r.status_code == 200
        block = next(b for b in r.text.split("\n\n") if "event: result" in b)
        data = next(l for l in block.split("\n") if l.startswith("data:"))[len("data:"):].strip()
        result = json.loads(data)
        pairs = sorted(
            (json.loads(p) for p in re.findall(r"event: pair\ndata: (.+)", r.text)),
            key=lambda p: p["index"],
        )
        qa_actions = [(p["index"], p["action"], p["qa"]) for p in pairs]
        return result, qa_actions

    result1, qa1 = _run(1)
    result2, qa2 = _run(2)
    result4, qa4 = _run(4)

    for label, result, qa in (("smoothness=2", result2, qa2), ("smoothness=4", result4, qa4)):
        assert result["n_autopass"] == result1["n_autopass"], label
        assert len(result["flagged"]) == len(result1["flagged"]), label
        assert len(result["abstained"]) == len(result1["abstained"]), label
        assert qa == qa1, label
