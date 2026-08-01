import json

import pytest
from fastapi.testclient import TestClient


@pytest.fixture(autouse=True)
def _restore_app_repository():
    """These tests swap the process-wide session repository on app.state. Without
    restoring it the replacement leaks into every later test module — it took out
    14 tests in test_session_ownership before this fixture existed."""
    from service.app import app
    original = getattr(app.state, "session_repository", None)
    yield
    app.state.session_repository = original


def _events(text):
    out = []
    for block in text.split("\n\n"):
        name, data = None, ""
        for line in block.split("\n"):
            if line.startswith("event:"):
                name = line[6:].strip()
            elif line.startswith("data:"):
                data += line[5:].strip()
        if name and data:
            out.append((name, json.loads(data)))
    return out


def _client_with_session():
    from unittest.mock import MagicMock

    from service.app import app
    from service.sessions.repository import InMemorySessionRepository

    stored = {"cls": "pose_snap", "keys_suggested": 2, "confidence": "medium",
              "evidence": {"gap": 0.043}, "brief": "Place a breakdown at the overshoot."}

    def _pair(index, triage=None, action="needs_key"):
        p = MagicMock()
        p.index = index
        p.action = action
        p.route = None
        p.keys_requested = 2
        p.qa = MagicMock()
        p.qa.status = "abstain"
        p.qa.reason = ""
        p.correction = None
        p.triage = triage
        return p

    result = MagicMock()
    result.pairs = [_pair(0, stored), _pair(1, action="filled")]
    result.n_autopass = 0
    result.n_corrected = 0
    result.flagged = []
    result.abstained = [1]
    result.keys_requested_total = 2

    repo = InMemorySessionRepository()
    sid, _path = repo.create("copilot_session")
    repo.save_state(sid, {"result": result, "keys": [], "chat": [], "explanations": {}})
    app.state.session_repository = repo
    return TestClient(app), sid, repo


_PLAN = """{"steps": [
    {"target": "triage", "kind": "agent", "ask": "why refused?", "args": {"index": 0}},
    {"target": "open_board", "kind": "tool", "args": {"index": 0}},
    {"target": "rerun_session", "kind": "tool", "args": {"smoothness": 1}}
]}"""


def _fake_ask(say='{"say": "Draw 2 keys.", "tool": null}'):
    return lambda: (lambda prompt: _PLAN if "ORCHESTRATOR" in prompt else say)


def test_the_route_streams_the_conversation_then_the_decision(monkeypatch):
    import service.orchestration.api as api

    monkeypatch.setattr(api, "make_ask_fn", _fake_ask())
    client, sid, _repo = _client_with_session()
    resp = client.post(f"/session/{sid}/orchestrate/stream",
                       json={"message": "why was pair 0 refused, open it, rerun sm 1"})
    assert resp.status_code == 200
    events = _events(resp.text)
    names = [n for n, _ in events]
    assert "agent" in names
    assert names[-1] == "decision"
    agents = [d for n, d in events if n == "agent"]
    assert agents[0]["frm"] == "orchestrator"
    assert agents[0]["to"] == "triage"
    decision = events[-1][1]
    assert len(decision["steps"]) == 3
    assert decision["confirm_queue"][0]["tool"] == "rerun_session"


def test_an_unknown_session_is_404():
    client, _sid, _repo = _client_with_session()
    resp = client.post("/session/99999/orchestrate/stream", json={"message": "hi"})
    assert resp.status_code == 404


def test_the_turn_is_appended_to_the_chat_log(monkeypatch):
    import service.orchestration.api as api

    monkeypatch.setattr(api, "make_ask_fn", _fake_ask('{"say": "Done.", "tool": null}'))
    client, sid, repo = _client_with_session()
    client.post(f"/session/{sid}/orchestrate/stream", json={"message": "do the thing"})
    chat = repo.state_for(sid)["chat"]
    assert chat[-2]["role"] == "user"
    assert chat[-1]["role"] == "assistant"


def test_the_transcript_is_persisted_on_the_session(monkeypatch):
    import service.orchestration.api as api

    monkeypatch.setattr(api, "make_ask_fn", _fake_ask())
    client, sid, repo = _client_with_session()
    client.post(f"/session/{sid}/orchestrate/stream", json={"message": "do the thing"})
    transcript = repo.state_for(sid).get("transcript")
    assert transcript and transcript[0]["frm"] == "orchestrator"


def test_the_existing_agent_stream_route_still_exists():
    """Additive: the proven chat route must be untouched."""
    from service.app import app
    # app.routes holds opaque _IncludedRouter wrappers in this FastAPI version, so
    # the published schema is the reliable place to read the mounted paths from.
    paths = app.openapi()["paths"].keys()
    assert "/session/{sid}/agent/stream" in paths
    assert "/session/{sid}/orchestrate/stream" in paths
