"""The artist must never be shown the model's JSON envelope.

Seen in a signed-in browser 2026-08-03: the chat bubble rendered

    { "say": "Pair 0 passed QA, so no defect was circled, ...", "tool": null,
      "args": null, "ask": null, "followups": [ ... ] }

verbatim. The model double-encoded — it answered with a JSON document whose
`say` field held a stringified copy of that same document. `_decide_from_raw`
takes `doc["say"]` as prose and never asks whether it is itself an envelope, so
the envelope went straight to the screen.

Corroborated by the same turn: the printed JSON says `"tool": null`, yet a
"Repair a frame" card appeared — because the card came from the orchestration
confirm_queue, not from this reply. Two layers describing different things is
what made the double-encoding visible at all.
"""
import json

from service.assistant.agent import _decide_from_raw

_CTX = "pairs: 1"


def _state():
    from inbetween_copilot.pipeline.models import CopilotResult, PairResult
    pair = PairResult(0, "filled", None, None, None, 0, gap=0.01)
    return {"keys": ["a", "b"],
            "result": CopilotResult(pairs=[pair], keys_requested_total=0,
                                    flagged=[], n_autopass=1)}


def test_a_double_encoded_reply_shows_the_prose_not_the_envelope():
    inner = {"say": "Pair 0 passed QA, so no defect was circled.",
             "tool": None, "args": None, "ask": None, "followups": []}
    raw = json.dumps({"say": json.dumps(inner), "tool": None, "args": None,
                      "ask": None, "followups": []})

    out = _decide_from_raw(_state(), raw, _CTX)

    assert out["say"] == "Pair 0 passed QA, so no defect was circled."
    assert not out["say"].lstrip().startswith("{"), (
        "the JSON envelope reached the artist's screen"
    )


def test_an_ordinary_reply_is_untouched():
    """The unwrap must not fire on prose that merely mentions braces."""
    raw = json.dumps({"say": "The {gap} number is 0.05.", "tool": None,
                      "args": None, "followups": []})
    assert _decide_from_raw(_state(), raw, _CTX)["say"] == "The {gap} number is 0.05."


def test_a_say_that_is_json_without_a_say_key_is_left_alone():
    """Only an ENVELOPE is unwrapped. Arbitrary JSON the artist asked to see
    stays as written, or the fix would start eating legitimate answers."""
    raw = json.dumps({"say": '{"gap": 0.05, "tau_gate": 0.05}', "tool": None,
                      "args": None, "followups": []})
    assert _decide_from_raw(_state(), raw, _CTX)["say"] == '{"gap": 0.05, "tau_gate": 0.05}'
