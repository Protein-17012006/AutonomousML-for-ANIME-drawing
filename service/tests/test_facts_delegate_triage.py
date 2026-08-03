"""The audit measured routed 13/14, cooperated 0/14 — because SESSION FACTS
already carried the answer, so the director never needed to ask anyone. It also
carried the frozen brief, which is the string that got replayed."""
from inbetween_copilot.pipeline.models import CopilotResult, PairResult
from service.assistant.ask import build_session_context

BRIEF = "Draw two breakdown keys at the extremes of the walk arc."


class _Cfg:
    cadence_fps = 12
    smoothness = 2
    interpolator = "rife"
    tau_gate = 0.05


def _state():
    refused = PairResult(
        0, "needs_key", None, None, None, 2, gap=0.0581,
        triage={"cls": "pose_snap", "keys_suggested": 2, "confidence": "medium",
                "evidence": {"gap": 0.0581, "tau_gate": 0.05}, "brief": BRIEF})
    filled = PairResult(1, "filled", "rife", ["a", "m", "b"], None, 0, gap=0.0122)
    return {"keys": ["a", "b", "c"], "cfg": _Cfg(),
            "result": CopilotResult(pairs=[refused, filled],
                                    keys_requested_total=2,
                                    flagged=[], n_autopass=1)}


def test_the_brief_is_not_in_the_facts():
    assert BRIEF not in build_session_context(_state())


def test_the_class_is_not_in_the_facts():
    assert "pose_snap" not in build_session_context(_state())


def test_the_facts_say_who_to_ask():
    assert "held by triage" in build_session_context(_state())


def test_the_refused_pair_keeps_its_measurement():
    assert "gap=0.05810" in build_session_context(_state())


def test_the_ACCEPTED_pair_keeps_its_measurement_too():
    """Without this, "pair 5's gap looks bigger and it was not refused" has
    nothing to compare against — the question that started Spec 5."""
    assert "gap=0.01220" in build_session_context(_state())


def test_the_threshold_is_stated_once_for_the_session():
    ctx = build_session_context(_state())
    assert "tau_gate=0.05" in ctx


def test_a_pair_with_no_triage_gets_no_pointer():
    state = _state()
    state["result"].pairs = [state["result"].pairs[1]]
    assert "held by triage" not in build_session_context(state)
