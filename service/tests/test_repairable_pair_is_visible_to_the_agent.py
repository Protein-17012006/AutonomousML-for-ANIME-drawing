"""`image_edit` could never be proposed, because the agent could not see a mid.

Measured on the live deployment 2026-08-03: the agent proposed `image_edit` on
a pair whose generated frame demonstrably existed (`pair_mids` carried all seven
in the result event, and the agent's own reply said "pair 0 has a generated
frame"), and the server refused it every time.

`_valid_repairable` accepts a pair only if `pair.mid_url` or
`state["pair_mids"][index]` is set. `PairResult` has **no** `mid_url` field, and
`save_state` never persisted `pair_mids` — so both branches were empty for every
pair of every session and the validator returned False unconditionally.

This is the third instance of one shape: an artefact is generated, stored and
URL'd to the client, and passes every test that stops at the storage, while no
agent can see it. The fix for `pair_keys` sits four lines above the hole and its
comment describes this exact failure.
"""
import io

import numpy as np
import pytest
from PIL import Image

pytest.importorskip("fastapi")
from fastapi.testclient import TestClient

from service.app import app
from service.assistant.agent import _valid_repairable
from service.sessions.dependencies import default_session_repository

from .test_gate_env import _result_event


def _png(v: int) -> io.BytesIO:
    b = io.BytesIO()
    Image.fromarray(np.full((16, 16, 3), v, np.uint8)).save(b, "PNG")
    b.seek(0)
    return b


def _run_filled_session() -> int:
    """Two keys one value-step apart: stub gap = mean|diff|/100 = 0.01 < 0.017,
    so the gate fills the pair and a mid is rendered."""
    c = TestClient(app)
    r = c.post("/session", data={"engines": "stub"}, files=[
        ("keys", ("0.png", _png(0), "image/png")),
        ("keys", ("1.png", _png(1), "image/png")),
    ])
    assert r.status_code == 200
    data = _result_event(r.text)
    assert data["needs_key"] == [], "the pair must be FILLED for this test to mean anything"
    assert data["pair_mids"], "the run rendered no mid at all; nothing to be visible"
    return int(data["artifacts"]["montage"].split("/")[2])


def test_the_saved_state_carries_the_rendered_mids():
    sid = _run_filled_session()
    state = default_session_repository.state_for(sid)
    assert state.get("pair_mids"), (
        "save_state dropped pair_mids, so every agent that asks whether a pair "
        "has a frame to paint on is told no"
    )


def test_a_filled_pair_with_a_mid_is_repairable():
    """The end the artist actually feels: the proposal survives validation."""
    sid = _run_filled_session()
    state = default_session_repository.state_for(sid)
    assert _valid_repairable({"index": 0}, len(state["result"].pairs), state) is True
