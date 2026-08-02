"""Two different questions about one pair used to return byte-identical text,
because `triage_agent` replayed a brief written once during the pipeline. And
the answer presented `pose_snap` — the residual bucket — as the gate's reason."""
from inbetween_copilot.triage.answer import (answer_refusal,
                                             deterministic_answer, prompt_for)

PAYLOAD = {
    "cls": "pose_snap",
    "keys_suggested": 2,
    "confidence": "medium",
    "evidence": {"gap": 0.058, "tau_gate": 0.05, "shift_frac": 0.108,
                 "regime": "small", "reading_what_moved": "the walking figure"},
    "brief": "Draw two breakdown keys at the extremes of the walk arc.",
}


def test_the_question_reaches_the_specialist_verbatim():
    seen = []

    def ask(prompt):
        seen.append(prompt)
        return "ok"

    answer_refusal("tại sao cặp 1 cần key?", PAYLOAD, ask)
    assert "tại sao cặp 1 cần key?" in seen[0]


def test_two_questions_do_not_produce_the_same_prompt():
    a = prompt_for("why does pair 1 need a key?", PAYLOAD)
    b = prompt_for("where exactly is the change?", PAYLOAD)
    assert a != b


def test_prompt_states_gap_and_the_threshold_it_was_compared_against():
    p = prompt_for("why?", PAYLOAD)
    assert "0.058" in p and "0.05" in p


def test_prompt_forbids_reporting_cls_as_the_reason():
    p = prompt_for("why?", PAYLOAD)
    assert "NEVER the reason" in p
    assert "RESIDUAL bucket" in p


def test_prompt_carries_the_comparison_caveat():
    assert "saturates" in prompt_for("why is pair 5 fine and pair 1 not?", PAYLOAD)


def test_prompt_carries_what_the_drawings_showed_when_it_was_read():
    assert "the walking figure" in prompt_for("what moved?", PAYLOAD)


def test_offline_answer_gives_the_real_reason_and_never_blames_cls():
    said = deterministic_answer(PAYLOAD, index=1)
    assert "0.058" in said and "0.05" in said
    assert "gate saw" not in said.lower()
    assert "detected" not in said.lower()


def test_offline_answer_survives_a_payload_with_no_measurements():
    said = deterministic_answer({"cls": "pose_snap"}, index=1)
    assert said.strip()
    assert "None" not in said


def test_a_dead_llm_costs_the_wording_not_the_answer():
    def boom(_prompt):
        raise RuntimeError("deepseek down")

    assert "0.058" in answer_refusal("why?", PAYLOAD, boom, index=1)


def test_an_empty_llm_reply_falls_back_rather_than_answering_nothing():
    assert answer_refusal("why?", PAYLOAD, lambda p: "  ", index=1).strip()


def test_no_llm_at_all_still_answers():
    assert "0.058" in answer_refusal("why?", PAYLOAD, None, index=1)
