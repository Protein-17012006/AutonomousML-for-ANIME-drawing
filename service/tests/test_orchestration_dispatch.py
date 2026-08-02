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


def test_a_rerun_that_changes_nothing_is_refused_on_the_orchestration_rail():
    """The chat rail and the orchestration rail read the SAME TOOLS table
    precisely so they cannot drift. A no-op re-run must die on both."""
    state = _state()
    state["cfg"] = MagicMock(engines="stub", cadence_fps=12, smoothness=1,
                             interpolator="rife")
    plan = Plan(goal="run it again", steps=(
        Step(1, "rerun_session", "tool", args={"smoothness": 1}),
    ))
    result = dispatch(AgentContext(state), plan)[0]
    assert result.status == "rejected"
    assert "refused" in result.says


def test_a_rerun_that_changes_something_still_queues_on_the_orchestration_rail():
    state = _state()
    state["cfg"] = MagicMock(engines="stub", cadence_fps=12, smoothness=1,
                             interpolator="rife")
    plan = Plan(goal="smoother", steps=(
        Step(1, "rerun_session", "tool", args={"smoothness": 2}),
    ))
    result = dispatch(AgentContext(state), plan)[0]
    assert result.status == "queued"


def test_run_plan_yields_one_pair_per_step_in_order():
    from service.orchestration.dispatch import run_plan
    produced = list(run_plan(AgentContext(_state()), _demo_plan()))
    assert [r.target for _entries, r in produced] == [
        "triage", "open_board", "rerun_session"]
    assert all(entries for entries, _r in produced)


def test_dispatch_and_run_plan_agree_step_for_step():
    """They must not drift: dispatch is now a thin drain of the same generator."""
    from service.orchestration.dispatch import run_plan
    ctx, plan = AgentContext(_state()), _demo_plan()
    via_generator = [r for _entries, r in run_plan(ctx, plan)]
    via_dispatch = dispatch(AgentContext(_state()), _demo_plan())
    assert [(r.target, r.status) for r in via_generator] == \
           [(r.target, r.status) for r in via_dispatch]


def test_run_plan_yields_nothing_for_an_empty_plan():
    from service.orchestration.dispatch import run_plan
    assert list(run_plan(AgentContext(_state()), Plan(goal="hi", steps=()))) == []


def _survey_state():
    """Pair 0 passed — no work, not actionable. Pair 1 is filled and flagged: the
    ONLY actionable pair in this cut, so first_index resolves to 1 purely by
    POSITION (it is the first, and only, actionable pair). cut_survey_agent sorts
    strictly by pair index, never by bucket type — do not make pair 0 `needs_key`
    to "test" a flag-outranks-needs_key ordering; that ordering was removed by
    Task 3 (see agents.py's Fix round 1) and asserting it here would reintroduce
    the exact bug those fixes exist to keep out."""
    result = MagicMock()
    result.pairs = [_pair(0, action="filled", qa_status="pass"),
                    _pair(1, action="filled", qa_status="flag")]
    result.n_autopass = 1
    result.n_corrected = 0
    result.flagged = [1]
    result.abstained = []
    result.keys_requested_total = 0
    return {"result": result, "keys": [], "chat": [], "explanations": {},
            "qa_degraded": False}


def test_a_later_step_reads_an_earlier_AGENTS_answer():
    from service.orchestration.dispatch import run_plan
    plan = Plan(goal="where do I start?", steps=(
        Step(1, "cut_survey", "agent", ask="order the cut", args={}),
        Step(2, "qa_csq", "agent", ask="verdict?", args={"index": "$1.first_index"}),
    ))
    results = [r for _e, r in run_plan(AgentContext(_survey_state()), plan)]
    assert results[0].status == "ok"
    # pair 0 passed (no work); the first ACTIONABLE pair is 1 — positional, not
    # ranked by bucket type.
    assert results[0].payload["first_index"] == 1
    assert results[1].status == "ok"
    assert results[1].payload["status"] == "flag"


def test_the_transcript_shows_BOTH_the_reference_and_what_it_resolved_to():
    """What is not rendered is indistinguishable from what did not happen."""
    from service.orchestration.dispatch import run_plan
    plan = Plan(goal="where do I start?", steps=(
        Step(1, "cut_survey", "agent", ask="order the cut", args={}),
        Step(2, "qa_csq", "agent", ask="verdict?", args={"index": "$1.first_index"}),
    ))
    produced = list(run_plan(AgentContext(_survey_state()), plan))
    ask_entry = produced[1][0][0]
    assert ask_entry.kind == "ask"
    assert ask_entry.data["index"] == 1
    assert ask_entry.data["_bound"] == {"index": "$1.first_index"}


def test_an_unresolvable_reference_REJECTS_the_step_and_the_plan_carries_on():
    from service.orchestration.dispatch import run_plan
    plan = Plan(goal="x", steps=(
        Step(1, "qa_csq", "agent", ask="verdict?", args={"index": "$9.first_index"}),
        Step(2, "qa_csq", "agent", ask="verdict?", args={"index": 0}),
    ))
    results = [r for _e, r in run_plan(AgentContext(_survey_state()), plan)]
    assert results[0].status == "rejected"
    assert "has not run" in results[0].says
    assert results[1].status == "ok"


def test_a_reference_to_a_field_the_agent_withheld_is_rejected():
    """cut_survey omits first_index when nothing needs work — a reference to it
    must fail loudly, not resolve to something invented."""
    from service.orchestration.dispatch import run_plan
    state = _survey_state()
    state["result"].pairs = [_pair(0, action="filled", qa_status="pass")]
    plan = Plan(goal="x", steps=(
        Step(1, "cut_survey", "agent", ask="order the cut", args={}),
        Step(2, "qa_csq", "agent", ask="verdict?", args={"index": "$1.first_index"}),
    ))
    results = [r for _e, r in run_plan(AgentContext(state), plan)]
    assert results[0].status == "ok"
    assert results[1].status == "rejected"
    # Pin the CAUSE, not just the status: "rejected" is also what a forward
    # reference to a step that never ran produces (see the previous test), and
    # a mis-keyed `sources` lookup can turn THIS failure into THAT one while
    # leaving the status unchanged. The withheld-field message says "did not
    # report"; the never-ran message says "has not run" — they must not be
    # interchangeable here.
    assert "did not report" in results[1].says


def test_a_resolved_value_still_passes_through_the_normal_tool_validator():
    """Binding opens no new trust boundary."""
    from service.orchestration.dispatch import run_plan
    plan = Plan(goal="x", steps=(
        Step(1, "cut_survey", "agent", ask="order the cut", args={}),
        Step(2, "open_board", "tool", args={"index": "$1.n_pairs"}),
    ))
    results = [r for _e, r in run_plan(AgentContext(_survey_state()), plan)]
    # n_pairs is 2 for a 2-pair session; valid indices are 0..n_pairs-1, so
    # n_pairs itself is out of range BY CONSTRUCTION — unlike keys_outstanding,
    # this does not depend on which pairs happen to be needs_key.
    assert results[1].status == "rejected"
    # The reference must actually have been RESOLVED before the validator saw
    # it — not merely "some value, rejected either way". An unresolved literal
    # "$1.n_pairs" is also not an int and would ALSO be rejected by
    # _valid_index, so a bare status check here cannot tell a real resolution
    # from a broken one that skips resolve_args entirely. Pin the concrete
    # resolved value the validator was actually handed.
    assert results[1].payload["args"] == {"index": 2}


def test_a_handoff_on_a_fast_synchronous_result_survives_the_ms_rebuild():
    """CARRIED FINDING from Task 2's review, deferred to here: `run_step` used to
    rebuild a StepResult by hand-listing seven positional fields whenever
    `result.ms` was falsy (the fast synchronous path every early-return refusal
    takes). `StepResult` gained `handoff` after that reconstruction was written,
    so the hand-written version silently dropped it. Task 7 is the first task
    that actually sets `handoff` — if this regresses, Task 7's tests fail for a
    reason that looks unrelated to handoff.

    `dataclasses.replace` is the fix; this test pins it directly at `run_step`,
    not through `run_plan`, and forces the falsy-`ms` branch by leaving `ms`
    at its dataclass default (0)."""
    from service.orchestration.dispatch import Seq, run_step

    def handing_off(ctx, step):
        from service.orchestration.models import StepResult
        return StepResult(step_id=step.id, target="perception", kind="agent",
                          status="refused", says="not mine to answer",
                          handoff={"to": "qa_csq", "reason": "wrong agent"})
        # ms left at its default, 0 -- falsy, so run_step's timing rebuild fires.

    from service.orchestration import registry
    original = registry._AGENT_HANDLERS["perception"]
    registry.register_agent("perception", handing_off)
    try:
        step = Step(1, "perception", "agent", ask="?", args={"index": 0})
        _entries, result = run_step(AgentContext(_state()), step, Seq())
    finally:
        registry.register_agent("perception", original)

    assert result.handoff == {"to": "qa_csq", "reason": "wrong agent"}
    assert result.ms >= 0    # the rebuild DID fire (ms was 0 going in)


def test_a_plan_with_no_references_and_no_handoffs_behaves_exactly_as_before():
    """If the new layer does not fire, what runs is what ran yesterday."""
    results = dispatch(AgentContext(_state()), _demo_plan())
    assert [(r.target, r.kind, r.status) for r in results] == [
        ("triage", "agent", "ok"),
        ("open_board", "tool", "ok"),
        ("rerun_session", "tool", "queued"),
    ]
    assert all(r.handoff is None for r in results)
