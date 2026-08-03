"""The defect the artist found: asking two different questions about pair 1
returned the same text, because the agent replayed the stored brief."""
from inbetween_copilot.pipeline.models import CopilotResult, PairResult
from service.orchestration.agents import AgentContext, triage_agent
from service.orchestration.models import Step

STORED = {
    "cls": "pose_snap", "keys_suggested": 2, "confidence": "medium",
    "evidence": {"gap": 0.058, "tau_gate": 0.05, "shift_frac": 0.108},
    "brief": "Draw two breakdown keys at the extremes of the walk arc.",
}


def _state():
    pair = PairResult(0, "needs_key", None, None, None, 2,
                      triage=dict(STORED), gap=0.058)
    return {"result": CopilotResult(pairs=[pair], keys_requested_total=2,
                                    flagged=[], n_autopass=0)}


def _ask_echoing_the_question(prompt: str) -> str:
    return "ANSWER-FOR:" + prompt.split("QUESTION: ")[1].split("\nANSWER:")[0]


def _step():
    return Step(id=1, target="triage", kind="agent", args={"index": 0})


def test_two_questions_get_two_answers():
    state = _state()
    first = triage_agent(
        AgentContext(state, _ask_echoing_the_question,
                     "why does pair 1 need a key?"), _step())
    second = triage_agent(
        AgentContext(state, _ask_echoing_the_question,
                     "where exactly is the change?"), _step())
    assert first.says != second.says
    assert "why does pair 1 need a key?" in first.says


def test_the_stored_measurements_are_not_regenerated():
    result = triage_agent(
        AgentContext(_state(), _ask_echoing_the_question, "why?"), _step())
    assert result.payload == STORED


def test_without_an_llm_it_still_states_gap_and_tau():
    result = triage_agent(AgentContext(_state(), None, "why?"), _step())
    assert "0.058" in result.says and "0.05" in result.says


def test_it_still_reports_ok_so_synthesis_treats_it_as_an_answer():
    result = triage_agent(
        AgentContext(_state(), _ask_echoing_the_question, "why?"), _step())
    assert result.status == "ok"
