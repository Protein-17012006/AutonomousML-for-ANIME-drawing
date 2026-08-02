"""The artist asked "where in the image makes the large gap" and was told
"there's no single place to point at" — while `pair_1_keys.png`, the key-travel
overlay rendered for exactly that pair, sat in the session directory.

Measured on the live session (2026-08-03): gap 0.05032, hot_cell None. So the
"no localized hotspot" half was HONEST — no 3x3 cell beat the runner-up by 1.4x.
What was wrong is the "nothing to show" half, and the cause is structural:
`pair_keys` was returned to the client but never saved into session state
(service/sessions/service.py), so no agent could see it even if it looked.

Same shape as 2026-08-02: an artefact generated, stored and URL'd passes every
test that stops at the storage. Then the mark existed and no component read
`annotated_url`; here the overlay exists and the agent DENIES it.
"""
from inbetween_copilot.pipeline.models import CopilotResult, PairResult
from inbetween_copilot.triage.answer import prompt_for
from service.assistant.ask import build_session_context

STORED = {"cls": "pose_snap", "keys_suggested": 2, "confidence": "medium",
          "evidence": {"gap": 0.0503, "tau_gate": 0.05, "shift_frac": 0.10,
                       "hot_cell_searched": True},
          "brief": "Draw two breakdown keys at the extremes of the walk arc."}


def _state(overlay=True):
    pair = PairResult(0, "needs_key", None, None, None, 2, gap=0.0503,
                      triage=dict(STORED))
    state = {"keys": ["a", "b"],
             "result": CopilotResult(pairs=[pair], keys_requested_total=2,
                                     flagged=[], n_autopass=0)}
    if overlay:
        state["pair_keys"] = {"0": "/session/1/pair_0_keys.png"}
    return state


# --- the facts must know the overlay exists ---------------------------------

def test_facts_announce_the_key_travel_overlay():
    assert "key-travel overlay" in build_session_context(_state())


def test_facts_stay_silent_when_no_overlay_was_rendered():
    """Never promise an artefact that does not exist — the 2026-08-01 defect."""
    assert "key-travel overlay" not in build_session_context(_state(overlay=False))


# --- the specialist must be told, and told what NOT to say ------------------

def test_prompt_tells_the_specialist_the_overlay_exists():
    p = prompt_for("where is the gap?", STORED, index=0, overlay=True)
    assert "key-travel overlay" in p
    assert "never say there is nothing to show" in p.lower()


def test_prompt_omits_the_overlay_when_there_is_none():
    p = prompt_for("where is the gap?", STORED, index=0, overlay=False)
    assert "key-travel overlay" not in p


# --- "no cell stood out" must be STATED, not inferred from absence ----------

def test_a_searched_but_empty_hot_cell_is_stated_explicitly():
    """The key is simply absent when nothing stands out, so the model was left
    inferring 'not localized' from silence. Absence of a key is not evidence."""
    p = prompt_for("where?", STORED, index=0)
    assert "no single cell stood out" in p


def test_an_unsearched_payload_does_not_claim_a_search_happened():
    """The stub path never runs the localizer. Saying 'no cell stood out' there
    would report a measurement that was never taken."""
    payload = {**STORED, "evidence": {"gap": 0.0503, "tau_gate": 0.05}}
    assert "no single cell stood out" not in prompt_for("where?", payload, index=0)


def test_a_found_hot_cell_is_still_named():
    payload = {**STORED,
               "evidence": {**STORED["evidence"], "hot_cell": "bc",
                            "hot_cell_ratio": 1.8}}
    p = prompt_for("where?", payload, index=0)
    assert "hot_cell = bc" in p
    assert "no single cell stood out" not in p
