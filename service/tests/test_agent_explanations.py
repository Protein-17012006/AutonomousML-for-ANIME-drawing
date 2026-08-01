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
    """The marked image must exist. This test used to pass `{}` for explanations
    and still expect acceptance — it asserted the defect: the rail checked only
    that the index was in range, so the agent could offer a rendered artefact for
    a pair that has none."""
    raw = '{"say": "Here it is.", "tool": "show_annotated", "args": {"index": 1}}'
    out = decide_agent(
        _state({1: {"err_type": "ghosting", "region": "mc",
                    "explanation": "double image",
                    "annotated_url": "/session/3/pair_1_annotated.png"}}),
        "show me pair 1", [], lambda p: raw)
    assert out["action"]["tool"] == "show_annotated"
    assert out["action"]["needs_confirm"] is False


def test_show_annotated_rejects_an_out_of_range_index():
    raw = '{"say": "Here it is.", "tool": "show_annotated", "args": {"index": 25}}'
    out = decide_agent(_state({}), "show me pair 25", [], lambda p: raw)
    assert out["action"] is None
    assert out["rejected_tool"] == "show_annotated"


# --- what a gate-refused pair can and cannot be asked for ------------------------
#
# explain_pairs() skips any pair whose action is "needs_key": the gate refused it
# before interpolation, so there are no frames to perceive and nothing to circle.
# A pair like that therefore has NO explanation and NO annotated_url, ever.
#
# The agent used to offer both anyway ("I can pull up the detailed gate triage and
# annotated frame for that pair"), the index-range check passed it, and the client
# reported "Opened pair 1" — a success message for a tool that delivered nothing.

def _state_with_needs_key(explanations=None):
    result = MagicMock()
    result.pairs = [_pair(0, action="filled", qa_status="abstain"),
                    _pair(1, action="needs_key", qa_status="abstain")]
    result.n_autopass = 0
    result.n_corrected = 0
    result.flagged = []
    result.abstained = [0]
    result.keys_requested_total = 1
    return {"result": result, "keys": [], "chat": [],
            "explanations": explanations or {}}


def test_explain_pair_is_refused_for_a_gate_refused_pair():
    raw = '{"say": "Let me pull the triage.", "tool": "explain_pair", "args": {"index": 1}}'
    out = decide_agent(_state_with_needs_key(), "why 1 key need ?", [], lambda p: raw)
    assert out["action"] is None
    assert out["rejected_tool"] == "explain_pair"


def test_show_annotated_is_refused_when_no_marked_image_exists():
    raw = '{"say": "Here it is.", "tool": "show_annotated", "args": {"index": 1}}'
    out = decide_agent(_state_with_needs_key(), "show the marked frame", [],
                       lambda p: raw)
    assert out["action"] is None
    assert out["rejected_tool"] == "show_annotated"


def test_show_annotated_is_refused_when_the_explanation_has_no_image():
    """An explanation can exist while the annotated render does not."""
    raw = '{"say": "Here it is.", "tool": "show_annotated", "args": {"index": 0}}'
    out = decide_agent(
        _state_with_needs_key({0: {"err_type": "ghosting", "region": "mc"}}),
        "show the marked frame", [], lambda p: raw)
    assert out["action"] is None
    assert out["rejected_tool"] == "show_annotated"


def test_explain_pair_is_allowed_where_an_explanation_exists():
    raw = '{"say": "Here is why.", "tool": "explain_pair", "args": {"index": 0}}'
    out = decide_agent(
        _state_with_needs_key({0: {"err_type": "ghosting", "region": "mc",
                                   "explanation": "double image on the arm"}}),
        "why was pair 0 flagged?", [], lambda p: raw)
    assert out["action"]["tool"] == "explain_pair"


def test_open_board_is_still_allowed_for_a_gate_refused_pair():
    """Opening the board on a needs_key pair is exactly right — that is where the
    artist draws the key it asked for. Only the two tools that promise a rendered
    artefact are constrained."""
    raw = '{"say": "Opening it.", "tool": "open_board", "args": {"index": 1}}'
    out = decide_agent(_state_with_needs_key(), "open pair 1", [], lambda p: raw)
    assert out["action"]["tool"] == "open_board"
