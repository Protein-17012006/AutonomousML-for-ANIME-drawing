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