"""An agent turn must survive the browser that produced it.

Only `/ask` turns ever reached the durable transcript. An agent or orchestrated
turn — the ones carrying the planner/triage/perception exchange — was appended to
the service's in-process `state["chat"]`, which the UI has no route to read back.
So the conversation that demonstrates the multi-agent handoff existed on exactly
one machine, in one browser, for as long as its cache lived.

Persisting it is best-effort by design: the answer has already been produced (and
in the streaming routes already sent), so a storage failure must not turn a good
answer into an error the way `/ask` correctly does before it has answered.
"""
from __future__ import annotations

import json

import pytest

pytest.importorskip("fastapi")
from fastapi.testclient import TestClient

from service.session_history.models import QaTranscriptTurn


ORIGIN = "https://testserver"


class RecordingTranscripts:
    def __init__(self, fail=False):
        self.turns = []
        self.fail = fail

    def append_turn(self, pid, owner_sub, *, question, answer, grounded, **extra):
        if self.fail:
            raise RuntimeError("transcript store down")
        turn = QaTranscriptTurn(
            turn_id=f"t{len(self.turns)}", question=question, answer=answer,
            grounded=grounded, answered_at="2026-08-02T00:00:00Z", **extra)
        self.turns.append(turn)
        return turn


def _client(monkeypatch, transcripts, state):
    import service.app as app_mod
    from service.session_history.dependencies import get_optional_history_transcripts
    from service.sessions.http_dependencies import get_session_repository

    class Repo:
        states = {1: state}

        def state_for(self, sid):
            return self.states.get(sid)

        def save_state(self, sid, value):
            self.states[sid] = value

        def session_transaction(self, sid):
            from contextlib import nullcontext
            return nullcontext()

        def owner_for(self, sid):
            return "user-a"

    repo = Repo()
    app_mod.app.dependency_overrides[get_optional_history_transcripts] = lambda: transcripts
    app_mod.app.dependency_overrides[get_session_repository] = lambda: repo
    return TestClient(app_mod.app, base_url=ORIGIN), app_mod


def _state():
    class Pair:
        index = 0
        action = "filled"
        route = "rife"
        keys_requested = 0
        qa = None
        correction = None
        triage = None
        artist_verdict = None

    class Result:
        pairs = [Pair()]
        n_autopass = 1
        n_corrected = 0
        flagged = []
        abstained = []
        keys_requested_total = 0

    return {"result": Result(), "keys": [None, None], "chat": [],
            "explanations": {}, "published_pid": "pid-1"}


def test_an_agent_turn_is_written_to_the_durable_transcript(monkeypatch):
    transcripts = RecordingTranscripts()
    client, app_mod = _client(monkeypatch, transcripts, _state())
    monkeypatch.setattr(
        "service.assistant.agent.decide_agent",
        lambda *a, **k: {"say": "pair 0 passed", "action": None},
        raising=False)
    try:
        response = client.post("/session/1/agent", json={"message": "how is pair 0?"},
                               headers={"Origin": ORIGIN})
        assert response.status_code == 200, response.text
        assert len(transcripts.turns) == 1, "the agent turn was not persisted"
        turn = transcripts.turns[0]
        assert turn.question == "how is pair 0?"
        assert turn.answer == "pair 0 passed"
        # The reopened session must be able to tell an agent turn from an /ask
        # turn: only one of them carries a multi-agent exchange.
        assert turn.kind == "agent"
    finally:
        app_mod.app.dependency_overrides.clear()


def test_a_storage_failure_never_turns_a_good_answer_into_an_error(monkeypatch):
    transcripts = RecordingTranscripts(fail=True)
    client, app_mod = _client(monkeypatch, transcripts, _state())
    monkeypatch.setattr(
        "service.assistant.agent.decide_agent",
        lambda *a, **k: {"say": "pair 0 passed", "action": None},
        raising=False)
    try:
        response = client.post("/session/1/agent", json={"message": "how is pair 0?"},
                               headers={"Origin": ORIGIN})
        assert response.status_code == 200, response.text
        assert response.json()["say"] == "pair 0 passed"
    finally:
        app_mod.app.dependency_overrides.clear()


def test_the_turn_model_carries_the_multi_agent_exchange():
    """The whole point: reopening must show WHO said what, not just the reply."""
    turn = QaTranscriptTurn(
        turn_id="t1", question="why was pair 2 refused?",
        answer="it was not refused …", grounded=True,
        answered_at="2026-08-02T00:00:00Z",
        kind="agent",
        transcript=[
            {"frm": "orchestrator", "to": "triage", "kind": "ask", "text": "why?"},
            {"frm": "triage", "to": "perception", "kind": "ask",
             "text": "the gate accepted this pair"},
            {"frm": "perception", "to": "triage", "kind": "reply",
             "text": "blur in region none"},
        ],
    )
    restored = QaTranscriptTurn.model_validate(json.loads(turn.model_dump_json()))
    assert restored.kind == "agent"
    assert [e["frm"] for e in restored.transcript] == [
        "orchestrator", "triage", "perception"]


def test_an_old_snapshot_without_the_new_fields_still_loads():
    """Sessions published before this change must keep opening."""
    turn = QaTranscriptTurn.model_validate({
        "turn_id": "t0", "question": "q", "answer": "a", "grounded": True,
        "answered_at": "2026-08-01T00:00:00Z",
    })
    assert turn.kind == "ask" and turn.transcript == []
