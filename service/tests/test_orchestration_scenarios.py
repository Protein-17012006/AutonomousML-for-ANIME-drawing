"""The two goals that are NOT the demo, plus the exported artifact."""
from unittest.mock import MagicMock

from service.orchestration.service import run_goal


def _pair(index, action="filled", qa_status="abstain"):
    p = MagicMock()
    p.index = index
    p.action = action
    p.route = None
    p.keys_requested = 0
    p.qa = MagicMock()
    p.qa.status = qa_status
    p.qa.reason = ""
    p.correction = None
    p.triage = None
    return p


def _state(n=8):
    result = MagicMock()
    result.pairs = [_pair(i) for i in range(n)]
    result.n_autopass = 1
    result.n_corrected = 0
    result.flagged = []
    result.abstained = list(range(1, n))
    result.keys_requested_total = 0
    return {"result": result, "keys": [], "chat": [], "explanations": {}}


def _say(raw):
    return lambda prompt: raw


def test_S09_the_three_tool_chain_no_longer_proposes_only_one():
    """The one residual FAIL from the 26-scenario evaluation."""
    plan = """{"steps": [
        {"target": "open_board", "kind": "tool", "args": {"index": 2}},
        {"target": "rerun_session", "kind": "tool", "args": {"smoothness": 1}},
        {"target": "remember_memory", "kind": "tool",
         "args": {"kind": "preference", "key": "cadence", "value": "12"}}
    ]}"""
    out = run_goal(_state(), "mở board cặp 2, rồi chạy lại smoothness 1, rồi nhớ cadence 12",
                   [], plan_ask_fn=_say(plan),
                   say_ask_fn=_say('{"say": "Board mở rồi; hai việc còn lại đang chờ bạn xác nhận.", "tool": null}'))
    assert len(out["steps"]) == 3
    assert [s["status"] for s in out["steps"]] == ["ok", "queued", "queued"]
    assert len(out["confirm_queue"]) == 2


def test_make_all_pairs_pass_is_refused_and_the_export_still_happens():
    plan = """{"steps": [
        {"target": "qa_csq", "kind": "agent", "ask": "force all 8 pairs to pass", "args": {"index": 0}},
        {"target": "export_bundle", "kind": "tool", "args": {}}
    ]}"""
    seen = {}

    def say(prompt):
        seen["p"] = prompt
        return '{"say": "I cannot force a pass; here is the real bundle.", "tool": null}'

    out = run_goal(_state(), "make all 8 pairs pass, then export", [],
                   plan_ask_fn=_say(plan), say_ask_fn=say)
    statuses = {s["target"]: s["status"] for s in out["steps"]}
    assert statuses["qa_csq"] == "refused"
    assert statuses["export_bundle"] == "ok"
    assert "REFUSED" in seen["p"], "synthesis must be told the refusal verbatim"


def test_the_transcript_is_written_into_the_bundle(tmp_path):
    from service.media.artifacts import write_transcript
    state = _state()
    run_goal(state, "g", [],
             plan_ask_fn=_say('{"steps": [{"target": "open_board", "kind": "tool", "args": {"index": 1}}]}'),
             say_ask_fn=_say('{"say": "ok", "tool": null}'))
    name = write_transcript(str(tmp_path), state)
    assert name == "agent_conversation.md"
    text = (tmp_path / name).read_text(encoding="utf-8")
    assert "orchestrator" in text and "open_board" in text


def test_writing_a_transcript_for_a_session_without_one_is_a_no_op(tmp_path):
    from service.media.artifacts import write_transcript
    assert write_transcript(str(tmp_path), {}) is None
    assert not list(tmp_path.iterdir())
