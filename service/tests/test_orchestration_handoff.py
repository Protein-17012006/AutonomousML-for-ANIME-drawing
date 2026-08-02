from unittest.mock import MagicMock

from service.orchestration.agents import AgentContext
from service.orchestration.dispatch import run_plan
from service.orchestration.models import Plan, Step


def _pair(index, action="filled", qa_status="flag"):
    p = MagicMock()
    p.index = index
    p.action = action
    p.keys_requested = 0
    p.qa = MagicMock()
    p.qa.status = qa_status
    p.qa.reason = ""
    p.correction = None
    p.triage = None
    return p


def _finding(index=0):
    return {index: {"err_type": "broken_line", "region": "mc",
                    "explanation": "the arm outline breaks",
                    "annotated_url": "/pair_0_annotated.png"}}


def _state(explanations=None, keys=None):
    import numpy as np
    rng = np.random.default_rng(0)
    result = MagicMock()
    result.pairs = [_pair(0)]
    result.n_autopass = 0
    result.n_corrected = 0
    result.flagged = [0]
    result.abstained = []
    result.keys_requested_total = 0
    if keys is None:
        keys = [rng.integers(0, 255, (32, 32, 3), dtype=np.uint8) for _ in range(2)]
    return {"result": result, "keys": keys, "chat": [],
            "explanations": _finding() if explanations is None else explanations,
            "qa_degraded": False}


def _triage_plan():
    return Plan(goal="what is wrong with pair 0?", steps=(
        Step(1, "triage", "agent", ask="diagnose pair 0", args={"index": 0}),))


def test_a_refusing_triage_ROUTES_the_work_to_perception():
    produced = list(run_plan(AgentContext(_state()), _triage_plan()))
    results = [r for _e, r in produced]
    assert results[0].target == "triage" and results[0].status == "refused"
    assert results[1].target == "perception" and results[1].status == "ok"
    assert results[1].payload["err_type"] == "broken_line"


def test_the_transcript_shows_the_AGENT_asking_not_the_orchestrator():
    """The one line a flat list can never produce."""
    produced = list(run_plan(AgentContext(_state()), _triage_plan()))
    ask_entries = [e for entries, _r in produced for e in entries if e.kind == "ask"]
    handoff_ask = [e for e in ask_entries if e.to == "perception"]
    assert handoff_ask, [(e.frm, e.to) for e in ask_entries]
    assert handoff_ask[0].frm == "triage"


def test_no_handoff_when_perception_has_NOTHING_to_say():
    """CORRECTION 2 — do not spend a step to collect a second refusal, and do not
    let triage's prose promise an explanation that does not exist."""
    produced = list(run_plan(AgentContext(_state(explanations={})), _triage_plan()))
    results = [r for _e, r in produced]
    assert [r.target for r in results] == ["triage"]
    assert "perception" not in results[0].says.lower()


def test_triage_DOES_point_at_perception_when_a_finding_exists():
    produced = list(run_plan(AgentContext(_state()), _triage_plan()))
    assert "perception" in produced[0][1].says.lower()


def test_a_handoff_may_not_target_a_TOOL():
    """An agent must not queue an action the planner never proposed."""
    from service.orchestration.dispatch import _handoff_refusal
    from service.orchestration.models import StepResult
    result = StepResult(1, "triage", "agent", "refused",
                        handoff={"to": "rerun_session", "args": {"smoothness": 1}})
    assert "tool" in _handoff_refusal(result, False, set(), 1)


def test_a_handoff_is_only_honoured_from_a_REFUSAL():
    from service.orchestration.dispatch import _handoff_refusal
    from service.orchestration.models import StepResult
    result = StepResult(1, "triage", "agent", "ok",
                        handoff={"to": "perception", "args": {"index": 0}})
    assert "refusal" in _handoff_refusal(result, False, set(), 1)


def test_handoff_depth_is_one():
    from service.orchestration.dispatch import _handoff_refusal
    from service.orchestration.models import StepResult
    result = StepResult(1, "triage", "agent", "refused",
                        handoff={"to": "perception", "args": {"index": 0}})
    assert "depth" in _handoff_refusal(result, True, set(), 1)


def test_a_target_receives_at_most_one_handoff_per_turn():
    from service.orchestration.dispatch import _handoff_refusal
    from service.orchestration.models import StepResult
    result = StepResult(1, "triage", "agent", "refused",
                        handoff={"to": "perception", "args": {"index": 0}})
    assert "already" in _handoff_refusal(result, False, {"perception"}, 1)


def test_a_handoff_may_not_carry_a_reference():
    from service.orchestration.dispatch import _handoff_refusal
    from service.orchestration.models import StepResult
    result = StepResult(1, "triage", "agent", "refused",
                        handoff={"to": "perception", "args": {"index": "$1.cls"}})
    assert "plain values" in _handoff_refusal(result, False, set(), 1)


def test_a_handoff_is_dropped_when_the_step_budget_is_spent():
    from service.orchestration.dispatch import _handoff_refusal
    from service.orchestration.models import MAX_PLAN_STEPS, StepResult
    result = StepResult(1, "triage", "agent", "refused",
                        handoff={"to": "perception", "args": {"index": 0}})
    assert "budget" in _handoff_refusal(result, False, set(), MAX_PLAN_STEPS)


def test_a_DROPPED_handoff_is_recorded_in_the_transcript_not_swallowed():
    """Pinned to the DROP entry itself, not to any text in the transcript: triage's
    own refusal prose already contains the word "budget" ("My key budget was
    fitted on pairs the gate REFUSED..."), so a bare substring search over every
    entry's text would still pass with the budget check deleted from
    `_handoff_refusal` — proven by mutation. The drop must be tagged
    status=="handoff_dropped" AND its own text must name the budget."""
    plan = Plan(goal="x", steps=tuple(
        Step(i, "triage", "agent", ask="diagnose", args={"index": 0})
        for i in range(1, 6)))            # 5 steps: the budget is already spent
    produced = list(run_plan(AgentContext(_state()), plan))
    dropped = [e for entries, _r in produced for e in entries
              if e.data.get("status") == "handoff_dropped"]
    all_texts = [e.text for entries, _r in produced for e in entries]
    assert dropped, all_texts
    assert any("budget" in e.text for e in dropped), [e.text for e in dropped]


def test_no_handoff_offered_means_no_extra_entry():
    plan = Plan(goal="x", steps=(
        Step(1, "qa_csq", "agent", ask="verdict?", args={"index": 0}),))
    produced = list(run_plan(AgentContext(_state()), plan))
    assert len(produced) == 1
    assert len(produced[0][0]) == 2       # exactly one ask + one reply
