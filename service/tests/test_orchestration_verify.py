"""The reply the artist reads must be constrained by what the agents actually did.

Until now that was enforced by ASKING the model not to lie: `_findings_block`
carries `[READY TO PROPOSE — it has NOT run yet; never say it is done]` and
`[REFUSED — do not work around it]`, and each of those strings exists because of
a real incident. A prompt instruction is not an invariant.

What this layer can and cannot do is worth stating plainly, because overclaiming
here would be the exact failure the product exists to prevent:

  CANNOT — detect a free-prose completion claim. The agent answers in the
  artist's language, so "đã được thực hiện thành công rồi" has no token to match
  and never will. The prompt notes stay as the layer above.

  CAN — refuse three things a machine can see: an action that was just refused,
  a filename that does not exist, and a decimal measurement that appears nowhere
  in what the model was shown.
"""
from unittest.mock import MagicMock

import pytest

from service.orchestration.models import StepResult
from service.orchestration.verify import Violation, violations


def _state(**over):
    result = MagicMock()
    result.pairs = []
    result.n_autopass = 0
    result.n_corrected = 0
    result.flagged = []
    result.abstained = []
    result.keys_requested_total = 0
    state = {"result": result, "keys": [], "chat": [], "explanations": {},
             "pair_mids": {0: "/session/7/pair_0.png"}, "pair_keys": {}}
    state.update(over)
    return state


def _out(say: str, action=None):
    return {"say": say, "grounded": True, "action": action, "followups": []}


# --- There is no rule A, and that is a finding ---------------------------------

def test_offering_a_refused_tool_is_ALREADY_impossible_upstream():
    """The rule that was specified first and does not exist.

    "An action the server refused this turn must not be offered anyway" was
    written before this test. The test would not go red: `decide_agent`
    validates every proposal and hands back `action: None` plus `rejected_tool`
    when the server will not run it, so no such action ever reaches synthesis.
    The only turn a rule could have fired on is a re-proposal of the same tool
    with different, VALID arguments — which is legitimate. It would have fired
    only on false positives, so it was dropped.

    This test freezes the reason. If `decide_agent` ever stops nulling the
    action, it goes red and the rule becomes worth writing.
    """
    from service.assistant.agent import decide_agent

    state = _state()
    state["result"].pairs = [MagicMock(index=0)]
    out = decide_agent(
        state, "repair pair 9", [],
        ask_fn=lambda p: '{"say": "Repairing now.", "tool": "image_edit", '
                         '"args": {"index": 9}}')
    assert out["action"] is None
    assert out["rejected_tool"] == "image_edit"


def test_a_queued_tool_offered_as_the_action_is_not_a_violation():
    """The normal path: dispatch queues a tool and synthesis offers it. Nothing
    here may fire, or every confirm-gated turn breaks."""
    queued = StepResult(1, "rerun_session", "tool", "queued",
                        says="Re-run session is ready and waiting on your confirmation.")
    assert violations(_out("Re-running is ready for you to confirm.",
                           action={"tool": "rerun_session", "args": {"smoothness": 1}}),
                      [queued], _state(), findings="") == []


# --- Rule B: an artefact that does not exist ---------------------------------

def test_naming_a_file_that_does_not_exist_is_a_hard_violation():
    found = violations(_out("I have marked it up in pair_4_annotated.png for you."),
                       [], _state(), findings="")
    assert [v.rule for v in found] == ["B"]
    assert "pair_4_annotated.png" in found[0].message


def test_a_file_the_session_really_has_passes():
    assert violations(_out("The in-between is at /session/7/pair_0.png."),
                      [], _state(), findings="") == []


def test_a_file_named_in_the_findings_passes():
    """Whatever a specialist put in front of the model is legitimate to repeat —
    the rule exists to catch invention, not quotation."""
    findings = "  perception (agent) -> ok: defect in the arm; see pair_2_vlm.png"
    assert violations(_out("Perception marked it in pair_2_vlm.png."),
                      [], _state(), findings=findings) == []


def test_the_canonical_run_artefacts_pass_without_being_listed():
    assert violations(_out("The report is in report.md and the montage in montage.png."),
                      [], _state(), findings="") == []


# --- Rule C: a measurement from nowhere --------------------------------------

def test_a_decimal_that_appears_nowhere_is_a_soft_violation():
    findings = "  triage (agent) -> ok: refused\n      measured: gap=0.0503, tau_gate=0.05"
    found = violations(_out("The gap measured 0.0821, over the threshold."),
                       [], _state(), findings=findings)
    assert [v.rule for v in found] == ["C"]
    # SOFT on purpose: synthesis legitimately derives figures, and a false alarm
    # must never be able to throw away a good answer.
    assert found[0].severity == "soft"


@pytest.mark.parametrize("say", [
    "The gap measured 0.0503, just over the threshold.",   # verbatim
    "The gap is about 0.05 — right on the line.",          # rounded: a prefix
    "That is a 5% whole-frame difference.",                # percent of 0.05
    "Three of the seven pairs are clean.",                 # words, not digits
    "Pairs 0, 1 and 2 passed; 4 keys were requested.",     # bare counts, derived
])
def test_rule_C_does_not_cry_wolf(say):
    """Every one of these is a legitimate sentence. Rule C is the rule most
    likely to raise a false alarm, so its false-positive cases are tested first
    class rather than discovered on the artist's screen."""
    findings = "  triage (agent) -> ok: refused\n      measured: gap=0.0503, tau_gate=0.05"
    assert violations(_out(say), [], _state(), findings=findings) == []


def test_bare_integers_are_never_a_violation_even_when_unfindable():
    """Counts are synthesised — "3 of 7" need not appear anywhere verbatim. Only
    DECIMAL measurements must be traceable; that is where fabrication is both
    likely and dangerous."""
    assert violations(_out("11 pairs, 4 of them flagged."), [], _state(),
                      findings="") == []


# --- Nothing wrong costs nothing ---------------------------------------------

def test_a_clean_reply_produces_no_violations():
    ok = StepResult(1, "triage", "agent", "ok", says="Draw 2 keys at the overshoot.")
    assert violations(_out("Triage asks for 2 keys at the overshoot."), [ok],
                      _state(), findings="") == []


def test_violation_is_reportable_in_plain_words():
    """The repair ask is read by the model, and the transcript line by a person."""
    v = Violation(rule="B", severity="hard", message="named 'ghost.png', "
                                                     "which this session does not have")
    assert "ghost.png" in v.message
