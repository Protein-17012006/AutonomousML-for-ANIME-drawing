"""End to end over the REAL routes, not the handlers in isolation.

A green unit suite proved nothing here once before: 545 passing tests and five
clean mutation runs, and the feature still refused every realistic request,
because a mock pins OUR contract with a dependency and never ITS contract with
us. So this drives `POST /session` and `POST /session/{sid}/agent` for real —
real gate, real plan, real facts sheet, real triage handler, real chat route.
Only the LLM is scripted, because there is no key offline.

What it pins is the artist's own complaint: two different questions about one
refused pair came back byte-identical, and the answer named `pose_snap` as the
reason the gate stopped it.
"""
import io
import json
import re

import numpy as np
import pytest
from PIL import Image

pytest.importorskip("fastapi")
from fastapi.testclient import TestClient

import service.app  # noqa: F401 — importing the composition root binds the runner
from service.app import app


def _png(v: int) -> io.BytesIO:
    b = io.BytesIO()
    Image.fromarray(np.full((8, 8, 3), v, np.uint8)).save(b, "PNG")
    b.seek(0)
    return b


def _result_event(body: str) -> dict:
    block = re.search(r"event: result\ndata: (.+)", body)
    assert block, f"no result event in: {body[:400]}"
    return json.loads(block.group(1))


# stub gap_fn = mean|b-a|/100: a value step of 20 scores gap 0.20, well above
# the calibrated default 0.017, so pair 0 is REFUSED and carries a triage payload.
_KEYS = [("keys", ("0.png", _png(0), "image/png")),
         ("keys", ("1.png", _png(20), "image/png"))]


class _ScriptedDirector:
    """Stands in for DeepSeek. Answers as triage when handed triage's prompt,
    and as the director otherwise — echoing the question so the test can tell
    the two turns apart by content rather than by call count."""

    def __init__(self):
        self.prompts = []

    def __call__(self, prompt: str) -> str:
        self.prompts.append(prompt)
        if "gap-triage specialist" in prompt:
            question = prompt.split("QUESTION: ")[1].split("\nANSWER:")[0]
            return f"TRIAGE<{question}>"
        if "SPECIALIST — you asked it" in prompt:
            relayed = prompt.split("report it faithfully and add nothing it "
                                   "did not say:\n  ")[1].split("\n")[0]
            return json.dumps({"say": relayed, "tool": None, "args": None,
                               "ask": None, "followups": []})
        return json.dumps({"say": "asking triage", "tool": None, "args": None,
                           "ask": {"name": "triage", "index": 0},
                           "followups": []})


@pytest.fixture
def client(monkeypatch):
    director = _ScriptedDirector()
    monkeypatch.setattr("service.infrastructure.director_llm.make_ask_fn",
                        lambda *a, **k: director)
    c = TestClient(app)
    r = c.post("/session", files=list(_KEYS), data={"engines": "stub"})
    assert r.status_code == 200
    result = _result_event(r.text)
    assert result["needs_key"] == [0], result
    c.sid = result["sid"]
    c.director = director
    return c


def _ask(client, message: str) -> dict:
    r = client.post(f"/session/{client.sid}/agent", json={"message": message})
    assert r.status_code == 200, r.text
    return r.json()


def test_two_questions_about_one_refused_pair_get_two_answers(client):
    """The defect, end to end. These two came back byte-identical."""
    first = _ask(client, "why does pair 0 need a key?")
    second = _ask(client, "the gap does not look large to me, why stop it?")
    assert first["say"] != second["say"]
    assert "why does pair 0 need a key?" in first["say"]
    assert "the gap does not look large to me" in second["say"]


def test_the_artists_words_reach_the_specialist_not_just_the_director(client):
    _ask(client, "chỗ nào là gap?")
    triage_prompts = [p for p in client.director.prompts
                      if "gap-triage specialist" in p]
    assert triage_prompts, "the specialist was never asked"
    assert any("chỗ nào là gap?" in p for p in triage_prompts)


def test_the_specialist_is_told_the_gap_AND_the_threshold(client):
    _ask(client, "why?")
    prompt = next(p for p in client.director.prompts
                  if "gap-triage specialist" in p)
    assert "gap = 0.2" in prompt
    assert "tau_gate = 0.017" in prompt


def test_the_specialist_is_forbidden_from_blaming_the_class(client):
    _ask(client, "why?")
    prompt = next(p for p in client.director.prompts
                  if "gap-triage specialist" in p)
    assert "NEVER the reason" in prompt
    assert "RESIDUAL bucket" in prompt


def test_the_facts_no_longer_hand_the_director_the_diagnosis(client):
    """If the brief were still in the facts the director could answer without
    asking anyone — which is why it never asked (audit: cooperated 0/14)."""
    _ask(client, "why?")
    director_prompts = [p for p in client.director.prompts
                        if "SESSION FACTS:" in p]
    assert director_prompts
    facts = director_prompts[0]
    assert "held by triage" in facts
    assert "large_action" not in facts and "pose_snap" not in facts


def test_the_accepted_and_refused_pairs_can_both_be_compared_on_gap(client):
    _ask(client, "why?")
    facts = next(p for p in client.director.prompts if "SESSION FACTS:" in p)
    assert "gap=0.20000" in facts
    assert "tau_gate=0.017" in facts
