"""Tests for service.app — POST /session SSE + GET artifact."""
import io
import numpy as np
import pytest
from PIL import Image

pytest.importorskip("fastapi")   # box cogvideo-venv only; skip (not error) off-box
from fastapi.testclient import TestClient
from service.app import app
from service.core.config import WebSettings

# The static UI mount is CONDITIONAL (`if _WEB_DIR.is_dir()` in service/app.py).
# This lineage ships no vanilla `web/` — the canonical UI is the team's Next.js
# export, deployed separately and served via COPILOT_WEB_DIR=dist. So the three
# tests below assert something that is true only where a UI directory is actually
# mounted; skip rather than fail where none is, instead of deleting a test that
# still guards the fallback UI wherever it is present.
_needs_ui = pytest.mark.skipif(
    not WebSettings.from_env().directory.is_dir(),
    reason="no UI directory mounted on this lineage (COPILOT_WEB_DIR is absent)")


def _png(v: int) -> io.BytesIO:
    b = io.BytesIO()
    Image.fromarray(np.full((8, 8, 3), v, np.uint8)).save(b, "PNG")
    b.seek(0)
    return b


@_needs_ui
def test_serves_ui_index():
    c = TestClient(app)
    r = c.get("/")
    assert r.status_code == 200
    assert "In-Between Co-pilot" in r.text and 'id="log"' in r.text


@_needs_ui
def test_serves_static_assets():
    c = TestClient(app)
    assert c.get("/app.js").status_code == 200
    assert c.get("/style.css").status_code == 200


@_needs_ui
def test_ui_exposes_demo_controls():
    """The demo-mode (decimate-vs-GT comparison) controls are wired into the served UI."""
    c = TestClient(app)
    assert 'id="demorun"' in c.get("/").text
    assert "/demo" in c.get("/app.js").text


def test_api_route_still_wins_over_mount():
    c = TestClient(app)
    r = c.post("/session", files=[("keys", ("0.png", _png(0), "image/png"))], data={"engines": "stub"})
    assert r.status_code == 400


def test_session_streams_pairs_then_result():
    c = TestClient(app)
    files = [
        ("keys", ("0.png", _png(0),   "image/png")),
        ("keys", ("1.png", _png(1),   "image/png")),
        ("keys", ("2.png", _png(128), "image/png")),
    ]
    r = c.post("/session", files=files, data={"engines": "stub"})
    assert r.status_code == 200
    assert "text/event-stream" in r.headers["content-type"]
    body = r.text
    assert "event: pair" in body
    assert body.count("event: result") == 1
    assert body.count("event: pair") >= 2
    assert body.index("event: pair") < body.index("event: result")


def test_session_echoes_selected_interpolator():
    import json
    import re

    c = TestClient(app)
    files = [
        ("keys", ("0.png", _png(0), "image/png")),
        ("keys", ("1.png", _png(1), "image/png")),
    ]
    r = c.post(
        "/session",
        files=files,
        data={"engines": "stub", "interpolator": "gimm"},
    )
    assert r.status_code == 200
    result = json.loads(
        re.search(r"event: result\ndata: (.+)", r.text).group(1)
    )
    assert result["sampling"]["interpolator"] == "gimm"


def test_session_rejects_unknown_interpolator():
    c = TestClient(app)
    files = [
        ("keys", ("0.png", _png(0), "image/png")),
        ("keys", ("1.png", _png(1), "image/png")),
    ]
    r = c.post(
        "/session",
        files=files,
        data={"engines": "stub", "interpolator": "unknown"},
    )
    assert r.status_code == 422


def test_session_rejects_one_key():
    c = TestClient(app)
    r = c.post(
        "/session",
        files=[("keys", ("0.png", _png(0), "image/png"))],
        data={"engines": "stub"},
    )
    assert r.status_code == 400


def test_artifact_download():
    """After a successful session the montage is downloadable."""
    c = TestClient(app)
    files = [
        ("keys", ("0.png", _png(5),  "image/png")),
        ("keys", ("1.png", _png(10), "image/png")),
    ]
    r = c.post("/session", files=files, data={"engines": "stub"})
    assert r.status_code == 200

    # extract sid from the result event artifact URL
    import json, re
    result_block = re.search(r"event: result\ndata: (.+)", r.text)
    assert result_block, "No result event found"
    data = json.loads(result_block.group(1))
    montage_url = data["artifacts"]["montage"]   # e.g. /session/1/montage.png

    r2 = c.get(montage_url)
    assert r2.status_code == 200


def test_artifact_404_unknown_session():
    c = TestClient(app)
    r = c.get("/session/999999/montage.png")
    assert r.status_code == 404


def test_artifact_traversal_rejected():
    """Path traversal via name should return 400, never 200 with foreign content."""
    c = TestClient(app)
    # First create a real session so the sid exists
    files = [
        ("keys", ("0.png", _png(0),  "image/png")),
        ("keys", ("1.png", _png(10), "image/png")),
    ]
    r = c.post("/session", files=files, data={"engines": "stub"})
    assert r.status_code == 200
    import json, re
    result_block = re.search(r"event: result\ndata: (.+)", r.text)
    assert result_block
    data = json.loads(result_block.group(1))
    # Extract the sid from the artifact URL e.g. /session/3/montage.png
    montage_url = data["artifacts"]["montage"]
    sid = int(montage_url.split("/")[2])
    # Attempt traversal: the TestClient may URL-encode, but the server should
    # still reject any path that resolves outside the session directory.
    r2 = c.get(f"/session/{sid}/../../etc/passwd")
    assert r2.status_code in (400, 404)
    # Must never be 200
    assert r2.status_code != 200


def test_export_bundle_zip():
    """Export: GET /session/{sid}/bundle.zip returns a zip of the usable artifacts."""
    import io as _io, json, re, zipfile
    c = TestClient(app)
    files = [
        ("keys", ("0.png", _png(5),  "image/png")),
        ("keys", ("1.png", _png(10), "image/png")),
    ]
    r = c.post("/session", files=files, data={"engines": "stub"})
    assert r.status_code == 200
    data = json.loads(re.search(r"event: result\ndata: (.+)", r.text).group(1))
    sid = int(data["artifacts"]["montage"].split("/")[2])

    rz = c.get(f"/session/{sid}/bundle.zip")
    assert rz.status_code == 200
    assert "application/zip" in rz.headers["content-type"]
    zf = zipfile.ZipFile(_io.BytesIO(rz.content))
    names = zf.namelist()
    assert any(n.endswith(".mp4") for n in names), names   # reconstructed video
    assert any(n.endswith(".png") for n in names), names   # montage / frames


def test_draw_key_refill_splits_gap():
    """POST /session/{sid}/key supplies a breakdown key for a gap -> the gap splits
    into two re-indexed sub-pairs in the returned (full) pair list."""
    import json, re
    c = TestClient(app)
    files = [
        ("keys", ("0.png", _png(0),   "image/png")),
        ("keys", ("1.png", _png(200), "image/png")),
    ]
    r = c.post("/session", files=files, data={"engines": "stub"})
    assert r.status_code == 200
    data = json.loads(re.search(r"event: result\ndata: (.+)", r.text).group(1))
    sid = int(data["artifacts"]["montage"].split("/")[2])

    rk = c.post(f"/session/{sid}/key",
                files=[("key", ("m.png", _png(100), "image/png"))],
                data={"index": "0"})
    assert rk.status_code == 200
    body = rk.json()
    assert len(body["pairs"]) == 2                       # one gap -> two sub-pairs
    assert [p["index"] for p in body["pairs"]] == [0, 1] # contiguous re-index
    assert "artifacts" in body["result"]


def test_draw_key_unknown_session():
    c = TestClient(app)
    rk = c.post("/session/999999/key",
                files=[("key", ("m.png", _png(1), "image/png"))], data={"index": "0"})
    assert rk.status_code == 404


def test_demo_returns_comparison_video():
    """POST /demo with a full cut returns a downloadable side-by-side compare.mp4."""
    c = TestClient(app)
    files = [("frames", (f"{i}.png", _png(i * 20), "image/png")) for i in range(5)]
    r = c.post("/demo", files=files, data={"engines": "stub"})
    assert r.status_code == 200
    data = r.json()
    assert data["video"].endswith("compare.mp4")
    assert data["frames"] == 5 and data["src"] == 3 and data["gt"] == 2
    r2 = c.get(data["video"])
    assert r2.status_code == 200 and len(r2.content) > 0


def test_demo_rejects_too_few_frames():
    c = TestClient(app)
    files = [("frames", (f"{i}.png", _png(i), "image/png")) for i in range(2)]
    r = c.post("/demo", files=files, data={"engines": "stub"})
    assert r.status_code == 400


def test_demo_respects_cadence_and_smoothness_fps():
    """Regression (final-review I2): /demo used to only read `fps: int = Form(24)` and
    silently drop the cadence/smoothness the web UI now posts, so the compare video
    always rendered at a fixed 24fps. cadence=8 x smoothness=1 must render at 8fps
    (SessionCfg's derived-fps path), not 24."""
    import os
    import tempfile

    import cv2

    c = TestClient(app)
    files = [("frames", (f"{i}.png", _png(i * 20), "image/png")) for i in range(5)]
    r = c.post("/demo", files=files, data={"engines": "stub", "cadence": "8", "smoothness": "1"})
    assert r.status_code == 200
    data = r.json()
    r2 = c.get(data["video"])
    assert r2.status_code == 200

    fd, path = tempfile.mkstemp(suffix=".mp4")
    os.close(fd)
    try:
        with open(path, "wb") as fh:
            fh.write(r2.content)
        cap = cv2.VideoCapture(path)
        fps = round(cap.get(cv2.CAP_PROP_FPS))
        cap.release()
    finally:
        os.remove(path)
    assert fps == 8   # cadence(8) * smoothness(1), NOT the old fixed 24


def test_session_smoothness_4_gated_returns_422(monkeypatch):
    """Merge-blocker (final-review I1a): POST /session with smoothness=4 must return
    an actionable 422 (pydantic ValidationError -> HTTPException), never a raw 500.

    ×4 was originally gated behind COPILOT_SMOOTHNESS_X4; it has since been DESCOPED
    outright — ×2 is the ceiling and the flag no longer exists in production code.
    The 422-not-500 guarantee is what this test is for and it is unchanged; only the
    detail wording moved, so assert the message the validator actually emits.
    Setting the retired flag must not change the outcome."""
    monkeypatch.setenv("COPILOT_SMOOTHNESS_X4", "1")   # retired flag: must not unlock
    c = TestClient(app)
    files = [
        ("keys", ("0.png", _png(0),  "image/png")),
        ("keys", ("1.png", _png(64), "image/png")),
    ]
    r = c.post("/session", files=files, data={"engines": "stub", "smoothness": "4"})
    assert r.status_code == 422
    assert "smoothness must be 1 or 2" in r.json()["detail"]


def test_session_invalid_smoothness_returns_422():
    """smoothness values outside {1,2,4} are rejected with 422, not 500 (closes the
    `smoothness not in {1,2,4}` reject-branch coverage gap)."""
    c = TestClient(app)
    files = [
        ("keys", ("0.png", _png(0),  "image/png")),
        ("keys", ("1.png", _png(64), "image/png")),
    ]
    r = c.post("/session", files=files, data={"engines": "stub", "smoothness": "3"})
    assert r.status_code == 422
    assert "smoothness" in r.json()["detail"]


def test_stream_session_assembles_frames_once_not_twice(monkeypatch):
    """M2 regression: `_stream_session` used to call `_assemble_frames` TWICE per
    session — once (directly) to compute the duration badge, and again inside
    `build_video`, and each assembly runs the (GPU, RIFE-backed) mid_engine per
    rife pair, so the duplicate assembly wastefully doubled RIFE work. The single
    assembly now lives in `service.media.rendering`, which reaches it as
    `artifacts._assemble_frames` and threads the result into `build_video(frames=...)`
    — so spying on the `service.media.artifacts` binding catches every call.

    (Rewritten: this test used to also patch a `service.sessions.streaming` binding
    and force `smoothness=4`. Streaming no longer imports `_assemble_frames` at all
    after the service re-modularization, and ×4 was descoped — ×2 is the ceiling —
    so both made the test fail for reasons unrelated to the invariant it guards.
    The invariant is factor-independent: assemble once per session, whatever the
    smoothness.)"""
    import service.media.artifacts as artifacts_mod

    calls = []
    orig = artifacts_mod._assemble_frames

    def _counting(*a, **k):
        calls.append(1)
        return orig(*a, **k)

    monkeypatch.setattr(artifacts_mod, "_assemble_frames", _counting)

    c = TestClient(app)
    files = [
        ("keys", ("0.png", _png(0), "image/png")),
        ("keys", ("1.png", _png(1), "image/png")),   # gap 0.01 < tau_gate -> FILLS
    ]
    r = c.post("/session", files=files, data={"engines": "stub", "smoothness": "2"})
    assert r.status_code == 200
    assert calls == [1], f"_assemble_frames called {len(calls)}x per session — expected exactly once"


def test_session_pair_order_matches_index():
    """Pairs arrive in ascending index order (verifies the worker emits in order)."""
    import json, re
    c = TestClient(app)
    files = [
        ("keys", ("0.png", _png(0),   "image/png")),
        ("keys", ("1.png", _png(64),  "image/png")),
        ("keys", ("2.png", _png(128), "image/png")),
    ]
    r = c.post("/session", files=files, data={"engines": "stub"})
    assert r.status_code == 200
    pairs = re.findall(r"event: pair\ndata: (.+)", r.text)
    assert len(pairs) >= 2
    indices = [json.loads(p)["index"] for p in pairs]
    assert indices == sorted(indices), f"pairs out of order: {indices}"


def test_result_event_carries_the_session_id():
    """The client must not have to parse an artifact URL to learn the sid.

    A published session is re-served with /sessions/{pid}/artifacts/... URLs, so
    URL-parsing silently yields no sid there and the grounded Q&A box goes dead.
    """
    import json
    import re

    c = TestClient(app)
    files = [
        ("keys", ("0.png", _png(5), "image/png")),
        ("keys", ("1.png", _png(10), "image/png")),
    ]
    r = c.post("/session", files=files, data={"engines": "stub"})
    assert r.status_code == 200

    data = json.loads(re.search(r"event: result\ndata: (.+)", r.text).group(1))
    sid_from_url = data["artifacts"]["montage"].split("/")[2]

    assert "sid" in data, "result event has no sid field"
    assert str(data["sid"]) == sid_from_url
