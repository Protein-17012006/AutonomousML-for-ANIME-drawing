"""COPILOT_TAU_GATE deployment override for the interpolable gate.

thresholds.py documents "tune per deployment; pass an explicit tau_gate to
override", but until 2026-07-23 no deployment lever existed: SessionCfg.tau_gate
was never wired into run_copilot, so the calibrated colored-anime default
(0.017) was hardcoded in production. Root-caused on line-art keys: the whole
gap_score range of that domain is 0.019-0.031 (even frame-vs-blank-white scores
0.031), which sits entirely ABOVE 0.017 -> every pair blocked NEEDS_KEY and a
drawn breakdown key could never unblock the session ("key requested" forever).
"""
import io
import json
import re

import numpy as np
import pytest
from PIL import Image

pytest.importorskip("fastapi")
from fastapi.testclient import TestClient

from service.app import app
from service.core.config import ConfigurationError, GateSettings


def _png(v: int) -> io.BytesIO:
    b = io.BytesIO()
    Image.fromarray(np.full((8, 8, 3), v, np.uint8)).save(b, "PNG")
    b.seek(0)
    return b


def _result_event(body: str) -> dict:
    block = re.search(r"event: result\ndata: (.+)", body)
    assert block, f"no result event in: {body[:400]}"
    return json.loads(block.group(1))


# stub gap_fn = mean|b-a|/100, so a value step of 2 scores gap 0.02:
# above the calibrated default TAU_GATE (0.017), below an 0.05 override.
_STEP2_KEYS = [
    ("keys", ("0.png", _png(0), "image/png")),
    ("keys", ("1.png", _png(2), "image/png")),
]


def test_gap_above_default_tau_blocks(monkeypatch):
    """Control: without the override the 0.02 pair still requests a key."""
    monkeypatch.delenv("COPILOT_TAU_GATE", raising=False)
    c = TestClient(app)
    r = c.post("/session", files=list(_STEP2_KEYS), data={"engines": "stub"})
    assert r.status_code == 200
    assert _result_event(r.text)["needs_key"] == [0]


def test_env_override_fills_previously_blocked_pair(monkeypatch):
    monkeypatch.setenv("COPILOT_TAU_GATE", "0.05")
    c = TestClient(app)
    r = c.post("/session", files=list(_STEP2_KEYS), data={"engines": "stub"})
    assert r.status_code == 200
    data = _result_event(r.text)
    assert data["needs_key"] == []
    assert data["n_autopass"] == 1


def test_add_key_rerun_honors_session_tau(monkeypatch):
    """The draw-a-key re-run must reuse the session's overridden tau: a 0.06 gap
    blocks under tau=0.05, and one drawn midpoint (two 0.03 sub-gaps) must
    unblock BOTH sub-pairs instead of re-requesting keys forever."""
    monkeypatch.setenv("COPILOT_TAU_GATE", "0.05")
    c = TestClient(app)
    files = [
        ("keys", ("0.png", _png(0), "image/png")),
        ("keys", ("1.png", _png(6), "image/png")),   # gap 0.06 >= 0.05 -> blocked
    ]
    r = c.post("/session", files=files, data={"engines": "stub"})
    assert r.status_code == 200
    data = _result_event(r.text)
    assert data["needs_key"] == [0]
    sid = int(data["artifacts"]["montage"].split("/")[2])

    rk = c.post(f"/session/{sid}/key",
                files=[("key", ("m.png", _png(3), "image/png"))],
                data={"index": "0"})
    assert rk.status_code == 200
    assert rk.json()["result"]["needs_key"] == []


def test_gate_settings_default_and_validation(monkeypatch):
    monkeypatch.delenv("COPILOT_TAU_GATE", raising=False)
    from inbetween_copilot.thresholds import TAU_GATE
    assert GateSettings.from_env().tau_gate == TAU_GATE

    monkeypatch.setenv("COPILOT_TAU_GATE", "0")
    with pytest.raises(ConfigurationError):
        GateSettings.from_env()

    monkeypatch.setenv("COPILOT_TAU_GATE", "not-a-number")
    with pytest.raises(ConfigurationError):
        GateSettings.from_env()
