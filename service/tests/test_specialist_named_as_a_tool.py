"""A specialist named in the `tool` field must be ASKED, not rejected.

Seen in a signed-in browser 2026-08-03. The artist asked to see the marked image
for pair 1 — a pair the gate REFUSED, so no marked image can exist. The agent
correctly said so and offered the one thing that does exist:

    "I can propose triage for pair 1, which will retrieve the gate diagnosis,
     the overlay, and the drawing brief."

and the artist got:

    "It suggested triage, but the server would not accept it — so nothing was
     proposed. Try asking a different way."

`triage` lives in SPECIALISTS, not TOOLS, and belongs in the `ask` field. The
model put it in `tool`; the lookup missed; the turn dead-ended. That is the
worst possible place for a dead end: ADR-0015 makes triage the ONLY route to a
refused pair's diagnosis, which is exactly what the artist had asked for.

Routing it is strictly safer than rejecting it: `_specialist_ask` still applies
the same whitelist and the same `_valid_specialist_pair` check, and a specialist
answer is data the director reports — never an artist-facing action.
"""
import json

from inbetween_copilot.pipeline.models import CopilotResult, PairResult
from service.assistant.agent import _decide_from_raw

_CTX = "pairs: 1"


def _refused_state():
    """One gate-refused pair — the only shape `triage` accepts."""
    pair = PairResult(0, "needs_key", None, None, None, 2, gap=0.0503,
                      triage={"cls": "pose_snap", "keys_suggested": 2})
    return {"keys": ["a", "b"],
            "result": CopilotResult(pairs=[pair], keys_requested_total=2,
                                    flagged=[], n_autopass=0)}


def test_triage_in_the_tool_field_is_routed_to_the_specialist():
    raw = json.dumps({"say": "Let me get the gate diagnosis for pair 0.",
                      "tool": "triage", "args": {"index": 0},
                      "ask": None, "followups": []})

    out = _decide_from_raw(_refused_state(), raw, _CTX)

    assert out["specialist"] == {"name": "triage", "index": 0}
    assert "rejected_tool" not in out, (
        "the artist was dead-ended on the one route to a refused pair's diagnosis"
    )


def test_an_explicit_ask_still_wins_over_a_misrouted_tool():
    """Do not let the salvage path overwrite a correctly-formed ask."""
    raw = json.dumps({"say": "checking", "tool": "triage", "args": {"index": 0},
                      "ask": {"name": "triage", "index": 0}, "followups": []})
    out = _decide_from_raw(_refused_state(), raw, _CTX)
    assert out["specialist"] == {"name": "triage", "index": 0}


def test_a_specialist_that_fails_its_own_check_is_still_refused():
    """Routing must not bypass the whitelist: triage on a FILLED pair has no
    gate diagnosis to fetch, and must not be silently accepted."""
    pair = PairResult(0, "filled", None, None, None, 0, gap=0.01)
    state = {"keys": ["a", "b"],
             "result": CopilotResult(pairs=[pair], keys_requested_total=0,
                                     flagged=[], n_autopass=1)}
    raw = json.dumps({"say": "checking", "tool": "triage", "args": {"index": 0},
                      "ask": None, "followups": []})
    out = _decide_from_raw(state, raw, _CTX)
    assert out["specialist"] is None
    assert out["action"] is None


def test_an_unknown_tool_is_still_reported_as_rejected():
    """The salvage path must not swallow a genuinely bad tool name."""
    raw = json.dumps({"say": "doing it", "tool": "delete_everything",
                      "args": {}, "ask": None, "followups": []})
    out = _decide_from_raw(_refused_state(), raw, _CTX)
    assert out["rejected_tool"] == "delete_everything"
    assert out["action"] is None
