from service.orchestration.models import (ENTRY_KINDS, MAX_PLAN_STEPS,
                                          MAX_TRANSCRIPT_ENTRIES, STATUSES,
                                          Plan, Step, StepResult, TranscriptEntry)


def test_the_five_statuses_are_frozen():
    assert STATUSES == ("ok", "refused", "queued", "rejected", "error")


def test_entry_kinds_are_frozen():
    assert ENTRY_KINDS == ("ask", "reply", "refuse", "queue", "error")


def test_caps():
    assert MAX_PLAN_STEPS == 5
    assert MAX_TRANSCRIPT_ENTRIES == 64


def test_a_step_defaults_to_no_args():
    step = Step(id=1, target="triage", kind="agent", ask="why refused?")
    assert step.args == {}


def test_an_empty_plan_carries_a_reason():
    plan = Plan(goal="do a thing", steps=(), reason="planner offline")
    assert plan.steps == ()
    assert plan.reason == "planner offline"
    assert not plan.is_actionable()


def test_a_populated_plan_is_actionable():
    plan = Plan(goal="g", steps=(Step(1, "open_board", "tool"),))
    assert plan.is_actionable()


def test_step_result_rejects_an_unknown_status():
    try:
        StepResult(step_id=1, target="triage", kind="agent", status="maybe")
    except ValueError as exc:
        assert "maybe" in str(exc)
    else:
        raise AssertionError("an unknown status must raise")


def test_transcript_entry_round_trips_through_a_dict():
    entry = TranscriptEntry(seq=0, frm="orchestrator", to="triage", kind="ask",
                            text="why was pair 1 refused?", data={"index": 1},
                            ms=12, ts=1.5)
    d = entry.as_dict()
    assert d["frm"] == "orchestrator" and d["to"] == "triage"
    assert TranscriptEntry(**d) == entry


def test_a_step_result_may_carry_a_handoff_and_defaults_to_none():
    from service.orchestration.models import StepResult
    plain = StepResult(1, "triage", "agent", "ok")
    assert plain.handoff is None
    routed = StepResult(1, "triage", "agent", "refused",
                        handoff={"to": "perception", "args": {"index": 2},
                                 "why": "the pair was filled"})
    assert routed.handoff["to"] == "perception"


def test_the_handoff_field_is_last_so_positional_construction_still_works():
    from service.orchestration.models import StepResult
    r = StepResult(1, "triage", "agent", "ok", "said", {"cls": "x"}, 12)
    assert r.says == "said" and r.payload == {"cls": "x"} and r.ms == 12
    assert r.handoff is None
