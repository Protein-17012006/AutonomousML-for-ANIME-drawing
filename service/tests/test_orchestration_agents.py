import numpy as np
from unittest.mock import MagicMock

from service.orchestration.agents import (AgentContext, perception_agent,
                                          qa_csq_agent, triage_agent)
from service.orchestration.models import Step


def _pair(index, action="filled", qa_status="abstain", triage=None):
    p = MagicMock()
    p.index = index
    p.action = action
    p.route = None
    p.keys_requested = 2 if action == "needs_key" else 0
    p.qa = MagicMock()
    p.qa.status = qa_status
    p.qa.reason = "u above tau"
    p.correction = None
    p.triage = triage
    return p


def _keys(n=3, size=32):
    rng = np.random.default_rng(0)
    return [rng.integers(0, 255, (size, size, 3), dtype=np.uint8) for _ in range(n)]


def _state(pairs, keys=None, explanations=None):
    result = MagicMock()
    result.pairs = pairs
    result.n_autopass = 0
    result.n_corrected = 0
    result.flagged = []
    result.abstained = [0]
    result.keys_requested_total = 0
    return {"result": result, "keys": keys if keys is not None else [],
            "chat": [], "explanations": explanations or {}}


def _ctx(state, ask_fn=None):
    return AgentContext(state=state, ask_fn=ask_fn)


# --- Triage -----------------------------------------------------------------

def test_triage_returns_the_stored_diagnosis_for_a_refused_pair():
    stored = {"cls": "pose_snap", "keys_suggested": 2, "confidence": "medium",
              "evidence": {"gap": 0.043}, "brief": "Place a breakdown at the overshoot."}
    state = _state([_pair(0, action="needs_key", triage=stored)], keys=_keys())
    out = triage_agent(_ctx(state), Step(1, "triage", "agent", args={"index": 0}))
    assert out.status == "ok"
    assert out.payload["keys_suggested"] == 2
    assert "overshoot" in out.says


def test_triage_REFUSES_a_key_count_for_a_pair_the_gate_accepted():
    """KEYS_EDGES is uncalibrated and classify_gap was fitted on wide pairs only."""
    state = _state([_pair(0, action="filled")], keys=_keys())
    out = triage_agent(_ctx(state), Step(1, "triage", "agent", args={"index": 0}))
    assert out.status == "refused"
    assert "keys_suggested" not in out.payload
    assert out.payload["out_of_population"] is True
    assert out.payload["cls"]                      # it still says WHAT it saw
    assert "key" in out.says.lower()               # and says it will not count keys


def test_triage_off_population_does_not_LEAK_a_key_count_in_its_prose():
    """Regression: the template brief reads "draw 3 breakdown key(s)", so emitting it
    alongside the refusal contradicted the refusal in the same sentence."""
    import re
    state = _state([_pair(0, action="filled")], keys=_keys())
    out = triage_agent(_ctx(state), Step(1, "triage", "agent", args={"index": 0}))
    assert "brief" not in out.payload
    assert not re.search(r"draw\s+\d+", out.says, re.I), out.says
    assert not re.search(r"\d+\s+breakdown", out.says, re.I), out.says
    assert out.payload["cls"]                       # measurements survive
    assert out.payload["evidence"]


def test_triage_off_population_payload_is_json_safe():
    """It travels into a TranscriptEntry and out through SSE."""
    import json
    state = _state([_pair(0, action="filled")], keys=_keys())
    out = triage_agent(_ctx(state), Step(1, "triage", "agent", args={"index": 0}))
    assert json.loads(json.dumps(out.payload))["cls"] == str(out.payload["cls"])


def test_triage_refuses_a_pair_that_does_not_exist():
    state = _state([_pair(0)], keys=_keys())
    out = triage_agent(_ctx(state), Step(1, "triage", "agent", args={"index": 25}))
    assert out.status == "refused"


def test_triage_refuses_when_the_key_drawings_were_not_retained():
    state = _state([_pair(0, action="filled")], keys=[])
    out = triage_agent(_ctx(state), Step(1, "triage", "agent", args={"index": 0}))
    assert out.status == "refused"
    assert "key" in out.says.lower()


def test_triage_contains_an_exploding_brief_writer():
    def boom(prompt):
        raise RuntimeError("deepseek exploded")

    state = _state([_pair(0, action="filled")], keys=_keys())
    out = triage_agent(_ctx(state, boom), Step(1, "triage", "agent", args={"index": 0}))
    assert out.status in ("refused", "error")      # never propagates


# --- Perception -------------------------------------------------------------

def test_perception_reports_what_the_vlm_saw():
    state = _state([_pair(0)], explanations={
        0: {"err_type": "broken_line", "region": "mc",
            "explanation": "the arm outline breaks", "annotated_url": "/x.png"}})
    out = perception_agent(_ctx(state), Step(1, "perception", "agent", args={"index": 0}))
    assert out.status == "ok"
    assert out.payload["err_type"] == "broken_line"
    assert out.payload["annotated_url"] == "/x.png"


def test_perception_refuses_when_it_never_examined_the_pair():
    state = _state([_pair(0, action="needs_key")], explanations={})
    out = perception_agent(_ctx(state), Step(1, "perception", "agent", args={"index": 0}))
    assert out.status == "refused"


# --- QA / CSQ ---------------------------------------------------------------

def test_qa_reports_the_calibrated_verdict():
    state = _state([_pair(0, qa_status="abstain")])
    out = qa_csq_agent(_ctx(state), Step(1, "qa_csq", "agent", args={"index": 0}))
    assert out.status == "ok"
    assert out.payload["status"] == "abstain"


def test_qa_REFUSES_to_move_the_bar():
    state = _state([_pair(0, qa_status="abstain")])
    step = Step(1, "qa_csq", "agent", ask="force all pairs to pass", args={"index": 0})
    out = qa_csq_agent(_ctx(state), step)
    assert out.status == "refused"
    assert "calibrat" in out.says.lower() or "conformal" in out.says.lower()


def test_importing_the_module_registers_every_agent():
    from service.orchestration import registry
    for name in ("triage", "perception", "qa_csq"):
        assert registry.resolve(name).handler is not None


def test_qa_refusal_CANNOT_be_laundered_by_a_paraphrasing_planner():
    """Live run 2026-08-01: the artist said "ép tất cả các cặp thành pass" and the
    planner relayed "what is your calibrated verdict for pair 3?" — the refusal never
    fired. The agent must read the artist's own words too."""
    state = _state([_pair(0, qa_status="abstain")])
    step = Step(1, "qa_csq", "agent", ask="what is your verdict for pair 0?",
                args={"index": 0})
    ctx = AgentContext(state=state, goal="Ép tất cả các cặp thành pass hết đi")
    out = qa_csq_agent(ctx, step)
    assert out.status == "refused"
    assert "calibrat" in out.says.lower() or "conformal" in out.says.lower()


def test_an_innocent_goal_still_gets_a_normal_verdict():
    state = _state([_pair(0, qa_status="abstain")])
    step = Step(1, "qa_csq", "agent", ask="what is the verdict?", args={"index": 0})
    ctx = AgentContext(state=state, goal="cặp 0 thế nào rồi?")
    out = qa_csq_agent(ctx, step)
    assert out.status == "ok"
    assert out.payload["status"] == "abstain"


def test_the_lower_the_bar_trigger_fires_on_real_vietnamese_and_english():
    from service.orchestration.agents import _LOWER_THE_BAR as R
    for s in ["Ép tất cả các cặp thành pass hết đi rồi export bundle cho tôi.",
              "Cứ ghi là cả 6 cặp đều pass hết rồi export bundle nhé.",
              "Hạ ngưỡng QA xuống để mấy cái abstain thành pass.",
              "force all 8 pairs to pass",
              "Can you force pass pair 3 as requested?",
              "đánh dấu hết thành pass đi",
              "bỏ qua abstain giúp tôi"]:
        assert R.search(s), f"must fire: {s}"


def test_the_lower_the_bar_trigger_does_not_fire_on_ordinary_questions():
    from service.orchestration.agents import _LOWER_THE_BAR as R
    for s in ["cặp 0 thế nào rồi?",
              "Session này có mấy cặp vậy?",
              "Cặp 3 bị từ chối. Tôi phải vẽ mấy key?",
              "what is your calibrated verdict for pair 3?",
              "mở board cặp 2 rồi chạy lại smoothness 1"]:
        assert not R.search(s), f"must NOT fire: {s}"
