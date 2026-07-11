"""SSE keepalive: the stream loop must emit `: ping` comments while the worker is
busy, so CloudFront's 60s origin *idle* timeout never fires on a slow first pair."""
import queue

from fastapi.testclient import TestClient

from service.app import app
from service.sessions.streaming import _drain_events


def test_drain_yields_ping_on_idle():
    q = queue.Queue()
    gen = _drain_events(q, keepalive=0.01)
    assert next(gen) == ("ping", None)          # nothing queued -> ping, not a hang
    q.put(("pair", "x"))
    assert next(gen) == ("pair", "x")           # real items pass through unchanged
    q.put(None)
    assert list(gen) == []                      # sentinel ends the generator


def test_drain_no_ping_when_items_flow():
    q = queue.Queue()
    q.put(("pair", 1))
    q.put(("result", 2))
    q.put(None)
    assert list(_drain_events(q, keepalive=5.0)) == [("pair", 1), ("result", 2)]


def test_stub_session_stream_still_well_formed(tmp_path):
    """Regression: the refactored loop keeps the exact SSE contract."""
    img = tmp_path / "k.png"
    from PIL import Image
    Image.new("RGB", (64, 64), (128, 128, 128)).save(img)
    client = TestClient(app)
    with open(img, "rb") as f1, open(img, "rb") as f2:
        r = client.post("/session", files=[("keys", ("a.png", f1, "image/png")),
                                           ("keys", ("b.png", f2, "image/png"))],
                        data={"engines": "stub"})
    assert r.status_code == 200
    body = r.text
    assert body.count("event: pair") >= 1
    assert body.count("event: result") == 1
    # any keepalive lines must be SSE *comments* (start with ':'), never break framing
    for line in body.splitlines():
        if line and not line.startswith(("event:", "data:", ":")):
            raise AssertionError(f"non-SSE line in stream: {line!r}")
