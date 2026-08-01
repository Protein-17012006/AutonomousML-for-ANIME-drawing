"""Grounded Q&A: fact-sheet builder + ask_fn + degrade path (box-free)."""
import json

from inbetween_copilot.generate.correction import CorrectionResult, CorrectionRound
from inbetween_copilot.pipeline.copilot import CopilotResult, PairResult
from inbetween_copilot.qa.gate import FrameQA
from service.assistant.ask import answer_question, build_session_context
from service.infrastructure.director_llm import make_ask_fn


def _state():
    corr = CorrectionResult("resolved", ["f"], [
        CorrectionRound("region_refill", None, None, reason="director: localized ghost")], 0, None)
    pairs = [
        PairResult(0, "filled", "rife", ["a", "m", "b"], FrameQA("pass", ""), 0),
        PairResult(1, "filled", "rife", ["a", "m", "b"],
                   FrameQA("flag", "csq:flag p=0.91 u=0.20"), 0, correction=corr),
        PairResult(2, "needs_key", None, None, None, 1),
    ]
    res = CopilotResult(pairs=pairs, keys_requested_total=1, flagged=[],
                        n_autopass=1, n_corrected=1)
    return {"keys": ["k0", "k1", "k2", "k3"], "result": res, "rev": 0}


def test_context_carries_pair_facts_and_totals():
    ctx = build_session_context(_state())
    assert "pair 1" in ctx and "flag" in ctx and "p=0.91" in ctx
    assert "region_refill" in ctx and "director: localized ghost" in ctx
    assert "needs_key" in ctx and "auto-pass: 1" in ctx and "corrected: 1" in ctx


def test_context_is_capped():
    st = _state()
    st["result"].pairs *= 400            # absurdly long session
    assert len(build_session_context(st)) <= 6000


def test_answer_grounded_via_ask_fn():
    out = answer_question(_state(), "why was pair 1 flagged?",
                          ask_fn=lambda prompt: "Pair 1 ghosted (p=0.91); the director re-filled the region.")
    assert out["grounded"] is True and "0.91" in out["answer"]


def test_answer_degrades_without_ask_fn():
    out = answer_question(_state(), "why?", ask_fn=None)
    assert out["grounded"] is False and "auto-pass" in out["answer"]   # template summary


def test_answer_degrades_when_ask_fn_fails():
    out = answer_question(_state(), "why?", ask_fn=lambda p: "")
    assert out["grounded"] is False


def test_make_ask_fn_returns_reply_text():
    def poster(url, body, headers):
        assert json.loads(body)["max_tokens"] >= 512
        return json.dumps({"choices": [{"message": {"content": "the answer"}}]})
    fn = make_ask_fn(api_key="k", model="deepseek-chat", poster=poster)
    assert fn("q") == "the answer"


def test_make_ask_fn_missing_key_and_failure():
    assert make_ask_fn(api_key="") is None
    fn = make_ask_fn(api_key="k", model="deepseek-chat",
                     poster=lambda u, b, h: (_ for _ in ()).throw(OSError("down")))
    assert fn("q") == ""


def test_ask_route_answers_from_state(monkeypatch):
    import pytest
    pytest.importorskip("fastapi")                      # box cogvideo-venv only
    from fastapi.testclient import TestClient
    import service.app as app_mod
    from service.core.auth import CurrentUser, require_current_user
    from service.session_history.dependencies import get_history_transcripts
    from service.sessions.dependencies import default_session_repository

    class TranscriptStore:
        def append_turn(self, pid, owner_sub, *, question, answer, grounded):
            assert (pid, owner_sub, question) == ("published-91", "test-user", "how many flagged?")
            return type("Turn", (), {"model_dump": lambda self: {"turn_id": "1"}})()

    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)   # force degrade path
    app_mod.app.dependency_overrides[require_current_user] = lambda: CurrentUser(
        sub="test-user", username="test-user", claims={}
    )
    app_mod.app.dependency_overrides[get_history_transcripts] = lambda: TranscriptStore()
    client = TestClient(app_mod.app)
    default_session_repository.states[91] = {**_state(), "published_pid": "published-91"}
    default_session_repository.paths[91] = "unused"
    try:
        r = client.post("/session/91/ask", json={"question": "how many flagged?"})
        assert r.status_code == 200
        j = r.json()
        assert "answer" in j and j["grounded"] is False      # no key in test env
        assert j["turn"] == {"turn_id": "1"}
        assert client.post("/session/999/ask", json={"question": "?"}).status_code == 404
    finally:
        app_mod.app.dependency_overrides.pop(require_current_user, None)
        app_mod.app.dependency_overrides.pop(get_history_transcripts, None)
        default_session_repository.states.pop(91, None)
        default_session_repository.paths.pop(91, None)
