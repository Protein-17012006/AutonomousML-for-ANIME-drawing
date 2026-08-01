from unittest.mock import MagicMock

from service.orchestration.service import run_goal


def _pair(index, action="needs_key", qa_status="abstain", triage=None):
    p = MagicMock()
    p.index = index
    p.action = action
    p.route = None
    p.keys_requested = 2
    p.qa = MagicMock()
    p.qa.status = qa_status
    p.qa.reason = ""
    p.correction = None
    p.triage = triage
    return p


def _state():
    stored = {"cls": "pose_snap", "keys_suggested": 2, "confidence": "medium",
              "evidence": {"gap": 0.043}, "brief": "Place a breakdown at the overshoot."}
    result = MagicMock()
    result.pairs = [_pair(0, triage=stored), _pair(1, action="filled")]
    result.n_autopass = 0
    result.n_corrected = 0
    result.flagged = []
    result.abstained = [1]
    result.keys_requested_total = 2
    return {"result": result, "keys": [], "chat": [], "explanations": {}}


_PLAN = """{"steps": [
    {"target": "triage", "kind": "agent", "ask": "why refused?", "args": {"index": 0}},
    {"target": "open_board", "kind": "tool", "args": {"index": 0}},
    {"target": "rerun_session", "kind": "tool", "args": {"smoothness": 1}}
]}"""


def test_the_demo_goal_end_to_end():
    seen = {}

    def say(prompt):
        seen["p"] = prompt
        return '{"say": "Draw 2 keys at the overshoot. Board is open; rerun is waiting.", "tool": null}'

    out = run_goal(_state(), "why was pair 0 refused, open it, rerun smoothness 1", [],
                   plan_ask_fn=lambda p: _PLAN, say_ask_fn=say)
    assert out["orchestrated"] is True
    assert len(out["steps"]) == 3
    assert len(out["confirm_queue"]) == 1
    assert out["confirm_queue"][0]["tool"] == "rerun_session"
    assert "overshoot" in out["say"]


def test_the_step_results_reach_the_synthesis_prompt():
    """One goal, several sub-tasks, recombined — the criterion, at the top level."""
    seen = {}

    def say(prompt):
        seen["p"] = prompt
        return '{"say": "ok", "tool": null}'

    run_goal(_state(), "g", [], plan_ask_fn=lambda p: _PLAN, say_ask_fn=say)
    prompt = seen["p"]
    assert "triage" in prompt
    assert "overshoot" in prompt          # the agent's own words
    assert "rerun_session" in prompt
    assert "waiting on your confirmation" in prompt


def test_a_queued_step_is_also_offered_as_the_single_action_for_old_clients():
    out = run_goal(_state(), "g", [], plan_ask_fn=lambda p: _PLAN,
                   say_ask_fn=lambda p: '{"say": "ok", "tool": null}')
    assert out["action"]["tool"] == "rerun_session"
    assert out["action"]["needs_confirm"] is True


def test_no_planner_falls_through_to_single_turn_chat():
    out = run_goal(_state(), "how many pairs?", [], plan_ask_fn=None,
                   say_ask_fn=lambda p: '{"say": "You have 2 pairs.", "tool": null}')
    assert out["orchestrated"] is False
    assert out["steps"] == []
    assert out["say"] == "You have 2 pairs."


def test_an_unplannable_goal_falls_through_to_single_turn_chat():
    out = run_goal(_state(), "hello", [], plan_ask_fn=lambda p: '{"steps": []}',
                   say_ask_fn=lambda p: '{"say": "Hi.", "tool": null}')
    assert out["orchestrated"] is False
    assert out["say"] == "Hi."


def test_a_failing_synthesis_still_reports_the_steps():
    def boom(prompt):
        raise RuntimeError("deepseek exploded")

    out = run_goal(_state(), "g", [], plan_ask_fn=lambda p: _PLAN, say_ask_fn=boom)
    assert out["orchestrated"] is True
    assert out["say"], "a synthesis failure must not yield an empty reply"
    assert "rerun_session" in out["say"] or "confirmation" in out["say"].lower()


def test_the_transcript_is_persisted_on_the_state():
    from service.orchestration.transcript import entries_for
    state = _state()
    run_goal(state, "g", [], plan_ask_fn=lambda p: _PLAN,
             say_ask_fn=lambda p: '{"say": "ok", "tool": null}')
    entries = entries_for(state)
    assert entries
    assert entries[0]["frm"] == "orchestrator"
    assert any(e["to"] == "orchestrator" for e in entries)


def test_live_entries_are_streamed_to_the_callback():
    seen = []
    run_goal(_state(), "g", [], plan_ask_fn=lambda p: _PLAN,
             say_ask_fn=lambda p: '{"say": "ok", "tool": null}', on_entry=seen.append)
    assert len(seen) == 6          # three steps, ask + reply each


def test_utterances_are_yielded_BEFORE_the_synthesis_runs():
    """Liveness: the transcript must not be a recording replayed after the turn.
    The synthesis call must not have happened while entries are still arriving."""
    from service.orchestration.service import run_goal_stream

    calls = {"say": 0}

    def say(prompt):
        calls["say"] += 1
        return '{"say": "ok", "tool": null}'

    stream = run_goal_stream(_state(), "g", [], plan_ask_fn=lambda p: _PLAN,
                             say_ask_fn=say)
    kind, payload = next(stream)
    assert kind == "agent"
    assert payload.frm == "orchestrator"
    assert calls["say"] == 0, "synthesis ran before the first utterance was emitted"

    kinds = [kind] + [k for k, _ in stream]
    assert kinds[-1] == "decision"
    assert kinds.count("agent") == 6


def test_an_ok_TOOL_is_never_described_to_synthesis_as_already_done():
    """Live run 2026-08-01 produced "Export bundle đã được thực hiện thành công rồi"
    and "Đã mở bảng đánh giá cặp 1 thành công" — both claimed an action ran that
    dispatch never executes."""
    seen = {}

    def say(prompt):
        seen["p"] = prompt
        return '{"say": "ok", "tool": null}'

    plan = '{"steps": [{"target": "export_bundle", "kind": "tool", "args": {}}]}'
    run_goal(_state(), "export it", [], plan_ask_fn=lambda p: plan, say_ask_fn=say)
    prompt = seen["p"]
    assert "has NOT run yet" in prompt
    assert "never say it is done" in prompt
    assert "NOTHING in this list has been executed" in prompt


def test_an_ok_AGENT_and_an_ok_TOOL_carry_different_notes():
    """An agent that answered really did answer; a tool that is `ok` did not run."""
    seen = {}

    def say(prompt):
        seen["p"] = prompt
        return '{"say": "ok", "tool": null}'

    plan = ('{"steps": [{"target": "triage", "kind": "agent", "args": {"index": 0}},'
            ' {"target": "open_board", "kind": "tool", "args": {"index": 0}}]}')
    run_goal(_state(), "g", [], plan_ask_fn=lambda p: plan, say_ask_fn=say)
    assert "(agent) -> ok [answered]" in seen["p"]
    assert "(tool) -> ok [READY TO PROPOSE" in seen["p"]
