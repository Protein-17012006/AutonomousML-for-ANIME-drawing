"""build_compare: box-style side-by-side ORIGINAL|RECON per session.

Left = the original (per-gap GT frame when the session has one, else the held
left key = the artist's stepped cadence), right = key + the pair's QA'd mid.
Frame-synced at cadence*2 fps — the box compare_video presentation.
"""
import numpy as np
import pytest

pytest.importorskip("imageio")
from service.media.artifacts import build_compare
from inbetween_copilot.pipeline.models import CopilotResult, PairResult


def _f(v):  # 8x8 uint8 frame
    return np.full((8, 8, 3), v, np.uint8)


def _filled(i, a, mid, b):
    return PairResult(i, "filled", "rife", [a, mid, b], None, 0)


def _needs_key(i):
    return PairResult(i, "needs_key", None, None, None, 1)


def _result(pairs):
    return CopilotResult(pairs=pairs, keys_requested_total=0, flagged=[],
                         n_autopass=0)


def test_png_flow_holds_key_as_original(tmp_path):
    keys = [_f(0), _f(100)]
    res = _result([_filled(0, keys[0], _f(50), keys[1])])
    name = build_compare(res, keys, str(tmp_path), fps=24)
    assert name == "compare.mp4" and (tmp_path / name).is_file()
    import imageio.v2 as imageio
    r = imageio.get_reader(str(tmp_path / name))
    meta = r.get_meta_data()
    assert round(meta["fps"]) == 24
    first = r.get_data(0)   # left key | divider | right key (identical keys)
    assert first.shape[1] > 8 * 2        # two panes + divider
    frame1 = r.get_data(1)  # left = HELD key(0) vs right = mid(50)
    left = frame1[:, :8].mean()
    right = frame1[:, -8:].mean()
    assert left < 20 and 35 < right < 65   # H.264 is lossy; generous bands


def test_video_flow_uses_real_gt(tmp_path):
    keys = [_f(0), _f(200)]
    res = _result([_filled(0, keys[0], _f(50), keys[1])])
    name = build_compare(res, keys, str(tmp_path), fps=24, gt_frames=[_f(90)])
    import imageio.v2 as imageio
    frame1 = imageio.get_reader(str(tmp_path / name)).get_data(1)
    assert 75 < frame1[:, :8].mean() < 105      # left = real GT (90)


def test_skipped_gap_keeps_sides_synced(tmp_path):
    keys = [_f(0), _f(60), _f(120)]
    res = _result([_needs_key(0), _filled(1, keys[1], _f(90), keys[2])])
    name = build_compare(res, keys, str(tmp_path), fps=24, gt_frames=[None, None])
    import imageio.v2 as imageio
    r = imageio.get_reader(str(tmp_path / name))
    assert r.count_frames() == 3   # key1, gt/mid, key2 — gap 0 skipped on both sides


def test_no_filled_pairs_returns_none(tmp_path):
    keys = [_f(0), _f(60)]
    assert build_compare(_result([_needs_key(0)]), keys, str(tmp_path), fps=24) is None


# --- e2e: the session pipeline renders and surfaces the artifact -------------

def _png(v: int):
    import io
    from PIL import Image
    b = io.BytesIO()
    Image.fromarray(np.full((8, 8, 3), v, np.uint8)).save(b, "PNG")
    b.seek(0)
    return b


def _result_event(body: str) -> dict:
    import json, re
    block = re.search(r"event: result\ndata: (.+)", body)
    assert block, f"no result event in: {body[:400]}"
    return json.loads(block.group(1))


def test_session_result_carries_compare_artifact():
    from fastapi.testclient import TestClient
    from service.app import app
    c = TestClient(app)
    files = [
        ("keys", ("0.png", _png(0), "image/png")),
        ("keys", ("1.png", _png(1), "image/png")),   # stub gap 0.01 < tau -> FILLS
    ]
    r = c.post("/session", files=files, data={"engines": "stub"})
    assert r.status_code == 200
    data = _result_event(r.text)
    assert "compare" in data["artifacts"], data["artifacts"]
    resp = c.get(data["artifacts"]["compare"])
    assert resp.status_code == 200
    assert resp.content[:12].find(b"ftyp") != -1 or len(resp.content) > 0


def test_needs_key_only_session_has_no_compare():
    from fastapi.testclient import TestClient
    from service.app import app
    c = TestClient(app)
    files = [
        ("keys", ("0.png", _png(0), "image/png")),
        ("keys", ("1.png", _png(200), "image/png")),  # stub gap 2.0 >> tau -> needs_key
    ]
    r = c.post("/session", files=files, data={"engines": "stub"})
    assert r.status_code == 200
    assert "compare" not in _result_event(r.text)["artifacts"]
