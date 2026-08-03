"""A plan fixed at t=0 keeps running against a premise that just died.

`plan_goal` is called once and `run_plan` then only drains a queue. The sole
adaptation is an agent-authored handoff — depth 1, only from a refusal. Late
binding protects a step that NAMES the dead one (it becomes `rejected`, "never
reached the specialist"), but an independent step still runs on the assumption
the refusal just destroyed.

This is the observe half of plan-act-observe, kept deliberately small: ONE
replan per turn, the not-yet-run tail only, inside the same 5-step budget, and
never a tool the original plan did not propose.
"""
from unittest.mock import MagicMock

from service.orchestration.agents import AgentContext
from service.orchestration.dispatch import dispatch
from service.orchestration.models import Plan, Step


def _pair(index, action="needs_key", triage=None):
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


def _state():
    result = MagicMock()
    result.pairs = [_pair(0), _pair(1, action="filled")]
    result.n_autopass = 0
    result.n_corrected = 0
    result.flagged = []
    result.abstained = [1]
    result.keys_requested_total = 2
    return {"result": result, "keys": [], "chat": [], "explanations": {}}


# triage refuses: pair 5 is not in this session, and no keys are stored either.
def _refusing_plan():
    return Plan(goal="explain pair 5 then open it", steps=(
        Step(1, "triage", "agent", ask="why refused?", args={"index": 5}),
        Step(2, "open_board", "tool", args={"index": 0}),
        Step(3, "export_bundle", "tool", args={}),
    ))


def _recorder(steps):
    """A replan port that records what it was told and answers with `steps`."""
    seen = []

    def replan(situation, remaining):
        seen.append((situation, remaining))
        return steps

    replan.seen = seen
    return replan


def test_a_refusal_asks_the_planner_to_reconsider_the_tail():
    replan = _recorder(())
    dispatch(AgentContext(_state()), _refusing_plan(), replan=replan)
    assert len(replan.seen) == 1
    situation, remaining = replan.seen[0]
    assert "triage" in situation and "refused" in situation.lower()
    # It must be told what is still queued, or it cannot decide what to keep.
    assert [s.target for s in remaining] == ["open_board", "export_bundle"]


def test_the_replanned_tail_replaces_the_original_one():
    replan = _recorder((Step(9, "open_board", "tool", args={"index": 1}),))
    results = dispatch(AgentContext(_state()), _refusing_plan(), replan=replan)
    assert [r.target for r in results] == ["triage", "open_board"]
    assert results[1].payload["args"] == {"index": 1}     # the NEW arguments


def test_only_one_replan_per_turn():
    """Two refusals must not become two planner calls: a turn has to end."""
    replan = _recorder((Step(9, "triage", "agent", args={"index": 7}),))
    dispatch(AgentContext(_state()), _refusing_plan(), replan=replan)
    assert len(replan.seen) == 1


def test_a_replan_may_not_introduce_a_tool_the_plan_never_proposed():
    """The same rule handoff already enforces. A tool step queues a button the
    artist never saw in the plan they were shown; an agent step only answers."""
    replan = _recorder((Step(9, "rerun_session", "tool", args={"smoothness": 1}),
                        Step(10, "open_board", "tool", args={"index": 1})))
    results = dispatch(AgentContext(_state()), _refusing_plan(), replan=replan)
    assert "rerun_session" not in [r.target for r in results]
    assert [r.target for r in results] == ["triage", "open_board"]


def test_nothing_is_replanned_when_no_work_remains():
    plan = Plan(goal="g", steps=(Step(1, "triage", "agent", args={"index": 5}),))
    replan = _recorder(())
    dispatch(AgentContext(_state()), plan, replan=replan)
    assert replan.seen == []


def test_an_unusable_replan_keeps_the_original_tail():
    """A planner that returns nothing usable must not silently delete planned
    work — "I could not re-plan" and "do less" are different answers, and only
    one of them is safe to assume."""
    results = dispatch(AgentContext(_state()), _refusing_plan(),
                       replan=lambda situation, remaining: None)
    assert [r.target for r in results] == ["triage", "open_board", "export_bundle"]


def test_a_refusal_that_produced_a_handoff_does_not_also_replan():
    """Two adaptation mechanisms in one turn are hard to reason about and harder
    to test. The agent's own choice of who to ask next wins."""
    from service.orchestration.models import StepResult

    def refuse_with_handoff(ctx, step):
        return StepResult(step.id, "triage", "agent", "refused",
                          says="not mine; perception has the frames",
                          handoff={"to": "perception", "args": {"index": 1},
                                   "why": "it has a finding"})

    from service.orchestration import registry
    original = registry.resolve("triage").handler
    registry.register_agent("triage", refuse_with_handoff)
    try:
        replan = _recorder(())
        results = dispatch(AgentContext(_state()), _refusing_plan(), replan=replan)
    finally:
        registry.register_agent("triage", original)
    assert replan.seen == []
    assert "perception" in [r.target for r in results]


def test_dispatch_without_a_replan_port_behaves_exactly_as_before():
    results = dispatch(AgentContext(_state()), _refusing_plan())
    assert [r.target for r in results] == ["triage", "open_board", "export_bundle"]
