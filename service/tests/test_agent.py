"""Tests for service/agent.py — UIA decide_agent."""
from unittest.mock import MagicMock
from service.agent import decide_agent


def _make_pair(index: int, action: str = "fill", qa_status: str = "pass"):
    pair = MagicMock()
    pair.index = index
    pair.action = action
    pair.route = None
    pair.keys_requested = 0
    pair.qa = MagicMock()
    pair.qa.status = qa_status
    pair.qa.reason = ""
    pair.correction = None
    pair.triage = None
    return pair


def _state():
    result = MagicMock()
    result.pairs = [_make_pair(0), _make_pair(1), _make_pair(2)]
    result.n_autopass = 3
    result.n_corrected = 0
    result.flagged = []
    result.abstained = []
    result.keys_requested_total = 0
    return {
        "keys": [b"fake_png_bytes"] * 3,
        "result": result,
        "cfg": MagicMock(engines="stub", cadence_fps=24, smoothness=1),
        "rev": {},
    }


def test_degrades_without_ask_fn():
    out = decide_agent(_state(), "hi", [], ask_fn=None)
    assert out["grounded"] is False and out["action"] is None
    assert "deterministic" in out["say"]


def test_plain_answer_no_tool():
    fn = lambda p: '{"say": "Pair 1 ghosted.", "tool": null, "args": null}'
    out = decide_agent(_state(), "why flagged?", [], ask_fn=fn)
    assert out == {"say": "Pair 1 ghosted.", "grounded": True, "action": None}


def test_valid_rerun_proposal_needs_confirm():
    fn = lambda p: '{"say": "Try x2.", "tool": "rerun_session", "args": {"smoothness": 2}}'
    out = decide_agent(_state(), "smoother please", [], ask_fn=fn)
    assert out["action"]["tool"] == "rerun_session"
    assert out["action"]["needs_confirm"] is True


def test_x4_rejected_server_side():
    fn = lambda p: '{"say": "ok", "tool": "rerun_session", "args": {"smoothness": 4}}'
    out = decide_agent(_state(), "give me x4", [], ask_fn=fn)
    assert out["action"] is None


def test_unknown_tool_dropped():
    fn = lambda p: '{"say": "ok", "tool": "run_planted", "args": {}}'
    out = decide_agent(_state(), "demo an error", [], ask_fn=fn)
    assert out["action"] is None


def test_non_json_reply_becomes_plain_answer():
    out = decide_agent(_state(), "hi", [], ask_fn=lambda p: "not json at all")
    assert out["grounded"] is True and out["action"] is None


def test_history_reaches_prompt():
    seen = {}
    def fn(p):
        seen["p"] = p
        return '{"say":"ok","tool":null,"args":null}'
    decide_agent(_state(), "and now?", [{"role": "user", "text": "make it smoother"}], ask_fn=fn)
    assert "make it smoother" in seen["p"]


# --- Task A2: POST /session/{sid}/agent (route) ---------------------------------
from fastapi.testclient import TestClient

from service import state as state_mod
from service.app import app


def test_agent_route_404_on_unknown_sid():
    c = TestClient(app)
    r = c.post("/session/999/agent", json={"message": "hi", "history": []})
    assert r.status_code == 404


def test_agent_route_degraded_shape(monkeypatch):
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)   # force degrade path
    state_mod._state[91] = _state()
    c = TestClient(app)
    r = c.post("/session/91/agent", json={"message": "hi", "history": []})
    assert r.status_code == 200
    body = r.json()
    assert body["grounded"] is False and body["action"] is None and body["say"]