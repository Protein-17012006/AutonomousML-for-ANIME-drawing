"""Perception findings reach the agent, and an artist can ask for the marked image."""
from unittest.mock import MagicMock

from service.assistant.agent import TOOLS, decide_agent
from service.assistant.ask import build_session_context


def _pair(index=0, action="filled", qa_status="abstain"):
    p = MagicMock()
    p.index = index
    p.action = action
    p.route = None
    p.keys_requested = 0
    p.qa = MagicMock()
    p.qa.status = qa_status
    p.qa.reason = ""
    p.correction = None
    p.triage = None
    return p


def _state(explanations):
    result = MagicMock()
    result.pairs = [_pair(0), _pair(1)]
    result.n_autopass = 0
    result.n_corrected = 0
    result.flagged = []
    result.abstained = [0]
    result.keys_requested_total = 0
    return {"result": result, "keys": [], "chat": [], "explanations": explanations}


def test_context_carries_the_perception_finding():
    ctx = build_session_context(_state({
        1: {"err_type": "broken_line", "region": "mc",
            "explanation": "the arm outline breaks mid-stroke",
            "annotated_url": "/session/3/pair_1_annotated.png"},
    }))
    assert "broken_line" in ctx
    assert "mc" in ctx
    assert "the arm outline breaks mid-stroke" in ctx


def test_string_keyed_explanations_are_matched_too():
    ctx = build_session_context(_state({"1": {"err_type": "ghosting", "region": "br",
                                              "explanation": "double image"}}))
    assert "ghosting" in ctx


def test_no_explanations_leaves_the_context_unchanged():
    ctx = build_session_context(_state({}))
    assert "vlm[" not in ctx


def test_show_annotated_is_a_read_only_tool():
    assert TOOLS["show_annotated"]["needs_confirm"] is False


def test_show_annotated_validates_the_pair_index():
    raw = '{"say": "Here it is.", "tool": "show_annotated", "args": {"index": 1}}'
    out = decide_agent(_state({}), "show me pair 1", [], lambda p: raw)
    assert out["action"]["tool"] == "show_annotated"
    assert out["action"]["needs_confirm"] is False


def test_show_annotated_rejects_an_out_of_range_index():
    raw = '{"say": "Here it is.", "tool": "show_annotated", "args": {"index": 25}}'
    out = decide_agent(_state({}), "show me pair 25", [], lambda p: raw)
    assert out["action"] is None
    assert out["rejected_tool"] == "show_annotated"
