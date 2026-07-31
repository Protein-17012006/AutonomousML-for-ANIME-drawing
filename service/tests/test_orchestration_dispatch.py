from unittest.mock import MagicMock

from service.orchestration.agents import AgentContext
from service.orchestration.dispatch import dispatch
from service.orchestration.models import Plan, Step


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


def _demo_plan():
    return Plan(goal="explain pair 0, open it, rerun at smoothness 1", steps=(
        Step(1, "triage", "agent", ask="why refused?", args={"index": 0}),
        Step(2, "open_board", "tool", args={"index": 0}),
        Step(3, "rerun_session", "tool", args={"smoothness": 1}),
    ))


def test_one_goal_produces_several_subtasks_reaching_named_specialists():
    """THE CRITERION TEST."""
    results = dispatch(AgentContext(_state()), _demo_plan())
    assert len(results) == 3
    assert [r.target for r in results] == ["triage", "open_board", "rerun_session"]
    assert [r.kind for r in results] == ["agent", "tool", "tool"]
    assert results[0].status == "ok"
    assert "overshoot" in results[0].says


def test_a_confirm_gated_tool_is_queued_and_never_executed():
    results = dispatch(AgentContext(_state()), _demo_plan())
    rerun = results[2]
    assert rerun.status == "queued"
    assert rerun.payload["needs_confirm"] is True
    assert rerun.payload["args"] == {"smoothness": 1}


def test_a_read_only_tool_is_marked_ok_not_queued():
    results = dispatch(AgentContext(_state()), _demo_plan())
    assert results[1].status == "ok"


def test_a_tool_failing_server_validation_is_rejected():
    plan = Plan(goal="g", steps=(Step(1, "open_board", "tool", args={"index": 25}),))
    results = dispatch(AgentContext(_state()), plan)
    assert results[0].status == "rejected"


def test_an_agent_refusal_is_not_retried_and_is_not_overwritten():
    """THE ADMISSION TEST, EXECUTABLE."""
    calls = []

    def refusing(ctx, step):
        from service.orchestration.models import StepResult
        calls.append(step.id)
        return StepResult(step_id=step.id, target="qa_csq", kind="agent",
                          status="refused", says="I will not move the bar.")

    from service.orchestration import registry
    original = registry._AGENT_HANDLERS["qa_csq"]
    registry.register_agent("qa_csq", refusing)
    try:
        plan = Plan(goal="make it all pass", steps=(
            Step(1, "qa_csq", "agent", ask="force pass", args={"index": 0}),
            Step(2, "export_bundle", "tool", args={}),
        ))
        results = dispatch(AgentContext(_state()), plan)
    finally:
        registry.register_agent("qa_csq", original)

    assert calls == [1], "a refusal must not be retried"
    assert results[0].status == "refused"
    assert results[0].says == "I will not move the bar."
    assert results[1].status == "ok", "the orchestrator must carry on after a refusal"


def test_a_handler_that_raises_becomes_an_error_and_the_plan_continues():
    def boom(ctx, step):
        raise RuntimeError("agent exploded")

    from service.orchestration import registry
    original = registry._AGENT_HANDLERS["perception"]
    registry.register_agent("perception", boom)
    try:
        plan = Plan(goal="g", steps=(
            Step(1, "perception", "agent", args={"index": 0}),
            Step(2, "open_board", "tool", args={"index": 0}),
        ))
        results = dispatch(AgentContext(_state()), plan)
    finally:
        registry.register_agent("perception", original)

    assert results[0].status == "error"
    assert results[1].status == "ok"


def test_the_transcript_records_who_asked_whom():
    seen = []
    dispatch(AgentContext(_state()), _demo_plan(), on_entry=seen.append)
    assert seen, "dispatch must emit transcript entries"
    asks = [e for e in seen if e.kind == "ask"]
    assert asks[0].frm == "orchestrator"
    assert asks[0].to == "triage"
    replies = [e for e in seen if e.kind in ("reply", "refuse", "queue")]
    assert replies[0].frm == "triage"
    assert replies[0].to == "orchestrator"
    assert [e.seq for e in seen] == list(range(len(seen)))


def test_an_empty_plan_dispatches_nothing():
    assert dispatch(AgentContext(_state()), Plan(goal="g", steps=())) == []
