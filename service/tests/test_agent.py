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
    assert out == {"say": "Pair 1 ghosted.", "grounded": True, "action": None,
                   "followups": []}


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
import re

import cv2
import numpy as np
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


# --- Task A3: POST /session/{sid}/rerun (confirmed action, real stub session) ----
def _png_bytes(shift: int) -> bytes:
    img = np.zeros((64, 64, 3), np.uint8)
    cv2.circle(img, (20 + shift, 32), 8, (255, 255, 255), -1)
    return cv2.imencode(".png", img)[1].tobytes()


def _open_stub_session(c: TestClient) -> int:
    files = [("keys", ("0000.png", _png_bytes(0), "image/png")),
             ("keys", ("0001.png", _png_bytes(6), "image/png"))]
    r = c.post("/session", files=files, data={"engines": "stub"})
    assert r.status_code == 200
    return int(re.search(r"/session/(\d+)/", r.text).group(1))


def test_rerun_streams_new_result_from_retained_keys():
    c = TestClient(app)
    sid = _open_stub_session(c)
    r = c.post(f"/session/{sid}/rerun", data={"smoothness": "1"})
    assert r.status_code == 200
    assert "event: result" in r.text        # same SSE contract as POST /session


def test_rerun_404_unknown_sid_and_422_bad_value():
    c = TestClient(app)
    assert c.post("/session/999/rerun", data={}).status_code == 404
    sid = _open_stub_session(c)
    assert c.post(f"/session/{sid}/rerun", data={"smoothness": "9"}).status_code == 422


# --- v1.1 hardening: server-side history + caps + prompt rules -------------------
def _capture_fn(seen):
    def fn(p):
        seen["p"] = p
        return '{"say":"ok","tool":null,"args":null}'
    return fn


def test_prompt_has_language_and_tool_restraint_rules():
    seen = {}
    decide_agent(_state(), "hi", [], ask_fn=_capture_fn(seen))
    assert "language of the user's LATEST message" in seen["p"]
    assert "ONLY when the user's request calls for" in seen["p"]


def test_history_turn_text_is_capped():
    seen = {}
    hist = [{"role": "user", "text": "z" * 10_000}]
    decide_agent(_state(), "hi", hist, ask_fn=_capture_fn(seen))
    assert len(seen["p"]) < 5_000


def test_user_message_is_capped():
    seen = {}
    decide_agent(_state(), "y" * 10_000, [], ask_fn=_capture_fn(seen))
    assert len(seen["p"]) < 5_000


def test_agent_route_keeps_history_server_side(monkeypatch):
    prompts = []

    def fake_make_ask_fn(**kw):
        def fn(p):
            prompts.append(p)
            return '{"say":"Pair 1 ghosted.","tool":null,"args":null}'
        return fn

    monkeypatch.setattr("service.director_llm.make_ask_fn", fake_make_ask_fn)
    state_mod._state[92] = _state()
    c = TestClient(app)
    c.post("/session/92/agent", json={"message": "why flagged?"})
    c.post("/session/92/agent", json={"message": "and now?"})
    assert "why flagged?" in prompts[1]        # user turn persisted server-side
    assert "Pair 1 ghosted." in prompts[1]     # assistant turn persisted too


# --- v1.2: SSE streaming ----------------------------------------------------------
def test_say_streamer_across_chunks_and_escapes():
    from service.agent import _SayStreamer
    s = _SayStreamer()
    parts = ['{"say', '": "Hel', 'lo \\"wo', 'rld\\"\\nok", "tool": null}']
    out = "".join(s.feed(p) for p in parts)
    assert out == 'Hello "world"\nok'
    assert s.raw == "".join(parts)


def test_decide_agent_stream_yields_say_deltas_then_decision():
    from service.agent import decide_agent_stream

    def fake_stream(p):
        yield '{"say": "Try '
        yield 'x2.", "tool": "rerun_session", "args": {"smoothness": 2}}'

    evs = list(decide_agent_stream(_state(), "smoother", [], fake_stream))
    says = [e["data"] for e in evs if e["event"] == "say"]
    assert "".join(says) == "Try x2."
    assert evs[-1]["event"] == "decision"
    assert evs[-1]["data"]["action"]["tool"] == "rerun_session"
    assert evs[-1]["data"]["action"]["needs_confirm"] is True


def test_decide_agent_stream_degrades_without_fn():
    from service.agent import decide_agent_stream
    evs = list(decide_agent_stream(_state(), "hi", [], None))
    assert [e["event"] for e in evs] == ["decision"]
    assert evs[0]["data"]["grounded"] is False


def test_agent_stream_route_sse_contract(monkeypatch):
    def fake_make_stream(**kw):
        def fn(p):
            yield '{"say": "Pair 1 ghosted.", "tool": null, "args": null}'
        return fn

    monkeypatch.setattr("service.director_llm.make_ask_stream_fn", fake_make_stream)
    state_mod._state[97] = _state()
    c = TestClient(app)
    r = c.post("/session/97/agent/stream", json={"message": "hi"})
    assert r.status_code == 200
    assert "event: say" in r.text and "event: decision" in r.text
    chat = state_mod._state[97]["chat"]
    assert chat[-1] == {"role": "assistant", "text": "Pair 1 ghosted."}


def test_make_ask_stream_fn_parses_deepseek_sse():
    from service.director_llm import make_ask_stream_fn
    lines = [
        b'data: {"choices":[{"delta":{"content":"He"}}]}\n',
        b'\n',
        b'data: {"choices":[{"delta":{"content":"llo"}}]}\n',
        b'data: [DONE]\n',
    ]
    fn = make_ask_stream_fn(api_key="k", opener=lambda url, body, headers: iter(lines))
    assert "".join(fn("p")) == "Hello"


def test_make_ask_stream_fn_none_without_key(monkeypatch):
    from service.director_llm import make_ask_stream_fn
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    assert make_ask_stream_fn() is None


# --- v1.2: regenerate + rate limit ------------------------------------------------
def test_regenerate_reasks_last_user_turn(monkeypatch):
    prompts = []

    def fake_make_ask_fn(**kw):
        def fn(p):
            prompts.append(p)
            return f'{{"say":"answer {len(prompts)}","tool":null,"args":null}}'
        return fn

    monkeypatch.setattr("service.director_llm.make_ask_fn", fake_make_ask_fn)
    state_mod._state[94] = _state()
    c = TestClient(app)
    c.post("/session/94/agent", json={"message": "why flagged?"})
    r = c.post("/session/94/agent", json={"regenerate": True})
    assert r.status_code == 200
    assert prompts[1].rstrip().endswith('USER: why flagged?\nJSON:')
    chat = state_mod._state[94]["chat"]
    assert [t["role"] for t in chat] == ["user", "assistant"]   # no duplicate turns
    assert chat[-1]["text"] == "answer 2"                       # fresh reply replaced old


def test_regenerate_422_when_nothing_to_regenerate():
    state_mod._state[95] = _state()
    c = TestClient(app)
    assert c.post("/session/95/agent", json={"regenerate": True}).status_code == 422


def test_agent_rate_limited_429(monkeypatch):
    monkeypatch.setenv("COPILOT_AGENT_RPM", "2")
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    state_mod._state[96] = _state()
    c = TestClient(app)
    assert c.post("/session/96/agent", json={"message": "1"}).status_code == 200
    assert c.post("/session/96/agent", json={"message": "2"}).status_code == 200
    assert c.post("/session/96/agent", json={"message": "3"}).status_code == 429


# --- v1.2: glossary tier + follow-ups --------------------------------------------
def test_prompt_includes_glossary():
    seen = {}
    decide_agent(_state(), "what does abstain mean?", [], ask_fn=_capture_fn(seen))
    assert "PRODUCT GLOSSARY" in seen["p"]
    assert "abstain" in seen["p"]


def test_followups_passthrough_and_capped_at_3():
    fn = lambda p: ('{"say":"ok","tool":null,"args":null,'
                    '"followups":["a?","b?","c?","d?"]}')
    out = decide_agent(_state(), "hi", [], ask_fn=fn)
    assert out["followups"] == ["a?", "b?", "c?"]


def test_followups_garbage_dropped():
    fn = lambda p: '{"say":"ok","tool":null,"args":null,"followups":"not a list"}'
    out = decide_agent(_state(), "hi", [], ask_fn=fn)
    assert out["followups"] == []


def test_agent_route_chat_turns_capped(monkeypatch):
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)   # degrade path still logs chat
    state_mod._state[93] = _state()
    c = TestClient(app)
    for i in range(12):
        c.post("/session/93/agent", json={"message": f"msg {i}"})
    assert len(state_mod._state[93]["chat"]) <= 16
