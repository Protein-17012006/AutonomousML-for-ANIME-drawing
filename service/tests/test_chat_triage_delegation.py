"""Orchestration only runs in Plan mode. With the diagnosis out of the facts,
ordinary chat would answer "I don't have that data" — so chat ASKS the same
specialist, through the same handler, and cannot diverge from Plan mode.

A specialist is not a tool. A tool is an artist-facing proposal that runs only on
confirmation; a specialist's answer is data. Keeping the two tables apart is also
what stops `triage` — already an orchestration AGENT — from being resolvable as a
tool, and keeps the assistant -> orchestration edge from existing at all."""
import pytest

from inbetween_copilot.pipeline.models import CopilotResult, PairResult
from service.assistant.agent import (SPECIALISTS, TOOLS, _decide_from_raw,
                                     _valid_specialist_pair)
from service.assistant import delegation

STORED = {"cls": "pose_snap", "keys_suggested": 2, "confidence": "medium",
          "evidence": {"gap": 0.058, "tau_gate": 0.05}, "brief": "Draw two keys."}


def _state(action="needs_key", triage=True):
    pair = PairResult(0, action, None, None, None, 2, gap=0.058,
                      triage=dict(STORED) if triage else None)
    return {"result": CopilotResult(pairs=[pair], keys_requested_total=2,
                                    flagged=[], n_autopass=0)}


def _asked():
    return {"say": "", "grounded": True, "followups": [], "action": None,
            "specialist": {"name": "triage", "index": 0}}


@pytest.fixture
def registered():
    """Bind a runner the way service/app.py does, and unbind it afterwards."""
    calls = []

    def runner(state, index, message, ask_fn):
        calls.append((index, message))
        return "gap 0.058 reached tau 0.05."

    delegation.set_specialist_runner("triage", runner)
    yield calls
    delegation._RUNNERS.pop("triage", None)


def _say(_prompt):
    return '{"say": "relayed", "tool": null, "args": null, "followups": []}'


# --- the whitelist -----------------------------------------------------------

def test_triage_is_refused_on_a_pair_that_was_never_refused():
    assert _valid_specialist_pair({"index": 0}, 1, _state("filled", triage=False)) is False


def test_triage_is_allowed_on_a_refused_pair():
    assert _valid_specialist_pair({"index": 0}, 1, _state()) is True


def test_a_true_index_cannot_address_pair_one():
    assert _valid_specialist_pair({"index": True}, 2, _state()) is False


def test_triage_is_a_specialist_and_NOT_a_tool():
    """It is already an orchestration agent. Putting it in TOOLS would make
    registry.resolve() return kind='agent' for something the planner is told is a
    tool, and would have forced assistant to import orchestration."""
    assert "triage" in SPECIALISTS
    assert "triage" not in TOOLS


# --- parsing -----------------------------------------------------------------

def test_a_proposed_ask_is_parsed_off_the_reply():
    out = _decide_from_raw(
        _state(),
        '{"say": "let me check", "tool": null, "args": null, '
        '"ask": {"name": "triage", "index": 0}, "followups": []}',
        "ctx")
    assert out["specialist"] == {"name": "triage", "index": 0}
    assert out["action"] is None, "asking a colleague is not an artist-facing action"


def test_an_ask_for_an_unknown_specialist_is_dropped():
    out = _decide_from_raw(
        _state(),
        '{"say": "x", "tool": null, "args": null, '
        '"ask": {"name": "nobody", "index": 0}, "followups": []}',
        "ctx")
    assert out["specialist"] is None


def test_an_ask_about_a_pair_the_gate_ACCEPTED_is_dropped():
    out = _decide_from_raw(
        _state("filled", triage=False),
        '{"say": "x", "tool": null, "args": null, '
        '"ask": {"name": "triage", "index": 0}, "followups": []}',
        "ctx")
    assert out["specialist"] is None


# --- the hop -----------------------------------------------------------------

def test_the_specialists_words_reach_the_second_pass(registered):
    seen = []

    def say(prompt):
        seen.append(prompt)
        return _say(prompt)

    out = delegation.resolve_specialist(
        _state(), "why was pair 0 refused?", _asked(), say)
    assert out["say"] == "relayed"
    assert any("gap 0.058 reached tau 0.05." in p for p in seen)


def test_the_artists_own_words_reach_the_specialist(registered):
    delegation.resolve_specialist(
        _state(), "gap trông không lớn mà?", _asked(), _say)
    assert registered == [(0, "gap trông không lớn mà?")]


def test_one_hop_per_turn(registered):
    """A second ask would loop; the answer is already in front of the director."""
    def say(_prompt):
        return ('{"say": "again", "tool": null, "args": null, '
                '"ask": {"name": "triage", "index": 0}, "followups": []}')

    out = delegation.resolve_specialist(_state(), "why?", _asked(), say)
    assert out["specialist"] is None
    assert len(registered) == 1


def test_a_turn_that_asked_nothing_is_returned_untouched(registered):
    original = {"say": "hello", "grounded": True, "action": None,
                "followups": [], "specialist": None}
    assert delegation.resolve_specialist(
        _state(), "hi", original, _say) is original


def test_with_no_runner_bound_the_turn_survives_unchanged():
    """Composition binds the handler. Without it the director simply answers from
    the facts — the same degradation an unreachable specialist would produce."""
    delegation._RUNNERS.pop("triage", None)
    asked = _asked()
    assert delegation.resolve_specialist(
        _state(), "why?", asked, _say) is asked
