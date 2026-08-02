from unittest.mock import MagicMock

from service.orchestration.agents import AgentContext
from service.orchestration.dispatch import run_plan
from service.orchestration.models import MAX_PLAN_STEPS, Plan, Step


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


# --- Fix round 1: unknown-target guard, loop cap, end-to-end tool block -----

def test_a_handoff_to_an_unknown_target_is_refused_not_raised():
    """Deleting `if target is None: return ...` (dispatch.py) leaves every other
    test in this file passing, then turns a bad `to` into an AttributeError
    ('NoneType' object has no attribute 'kind') inside _handoff_refusal — a
    raise where both _handoff_refusal and run_plan are documented never to
    raise. This is also the guard that blocks case variants, whitespace, empty
    strings and non-string values probed directly against `to`."""
    from service.orchestration.dispatch import _handoff_refusal
    from service.orchestration.models import StepResult
    bad_targets = ("not_a_real_agent", "PERCEPTION", " perception", "", None,
                  0, ["perception"])
    for bad_to in bad_targets:
        result = StepResult(1, "triage", "agent", "refused",
                            handoff={"to": bad_to, "args": {}})
        reason = _handoff_refusal(result, False, set(), 1)
        # The failure mode being guarded is a RAISE, not a wrong string — so the
        # call must simply return, and return something non-empty (a dropped
        # handoff, not a silently accepted one).
        assert isinstance(reason, str) and reason, (bad_to, reason)


def test_run_plan_caps_execution_at_MAX_PLAN_STEPS():
    """Changing `while queue and ran < MAX_PLAN_STEPS:` to `while queue:` leaves
    every other test in this file passing — a 7-step plan then runs 7 steps.
    `planner._steps_from` truncates at 5 today, which masks it; `Plan` is
    freely constructible and `run_plan` is the sole enforcement point."""
    plan = Plan(goal="x", steps=tuple(
        Step(i, "qa_csq", "agent", ask="verdict?", args={"index": 0})
        for i in range(1, 8)))            # 7 steps requested, cap is 5
    produced = list(run_plan(AgentContext(_state()), plan))
    assert len(produced) == MAX_PLAN_STEPS


def test_a_plan_truncated_by_the_budget_SAYS_SO_in_the_transcript():
    """A step beyond the cap must not just vanish: the old `for step in
    plan.steps` loop ran every step, so silently dropping the tail on the new
    cap is a behaviour change, and this task went to trouble to avoid exactly
    this kind of silent drop for handoffs. Pinned to the truncation entry's own
    `data["status"]`, not a bare text search — the handoff-drop path also says
    "budget" and must not be able to satisfy this assertion instead."""
    plan = Plan(goal="x", steps=tuple(
        Step(i, "qa_csq", "agent", ask="verdict?", args={"index": 0})
        for i in range(1, 8)))            # 7 requested, only 5 run -> 2 dropped
    produced = list(run_plan(AgentContext(_state()), plan))
    truncated = [e for entries, _r in produced for e in entries
                if e.data.get("status") == "plan_truncated"]
    all_texts = [e.text for entries, _r in produced for e in entries]
    assert truncated, all_texts
    assert truncated[0].data.get("not_run") == 2, truncated[0].data


def test_a_handoff_to_a_TOOL_is_blocked_end_to_end_through_run_plan(monkeypatch):
    """The six per-reason tests above call _handoff_refusal directly with
    hand-built StepResults, so they cannot tell whether run_plan actually
    consults it. Step(..., "agent") is decorative — run_step re-resolves the
    target through the registry by NAME, so a misbehaving (or malicious)
    agent handler is free to hand off to a tool name, and _handoff_refusal is
    the only thing standing between that and _run_tool actually queuing
    rerun_session. This drives a fake refusing handler through the real
    run_plan loop and checks the tool never ran."""
    from service.orchestration import registry

    def _fake_triage(ctx, step):
        from service.orchestration.models import StepResult
        return StepResult(step.id, step.target, "agent", "refused",
                          says="fake refusal handing off to a tool",
                          handoff={"to": "rerun_session",
                                   "args": {"smoothness": 1}})

    monkeypatch.setattr(registry, "_AGENT_HANDLERS",
                        {**registry._AGENT_HANDLERS, "triage": _fake_triage})

    produced = list(run_plan(AgentContext(_state()), _triage_plan()))
    results = [r for _e, r in produced]
    texts = [e.text for entries, _r in produced for e in entries]

    # rerun_session needs_confirm=True: if the tool guard were gone, this
    # handoff-born step would actually run _run_tool and come back "queued".
    assert all(r.status != "queued" for r in results), results
    assert all(r.target != "rerun_session" for r in results), results
    assert any("tool" in t for t in texts), texts
