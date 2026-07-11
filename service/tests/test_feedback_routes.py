"""Route tests for /session/{sid}/feedback (box-free, in-memory store)."""
import pytest

pytest.importorskip("fastapi")
from fastapi.testclient import TestClient

from inbetween_copilot.pipeline.copilot import CopilotResult, PairResult
from inbetween_copilot.qa.gate import FrameQA
from service.app import app
from service.feedback.adapters import InMemoryFeedbackStore
from service.sessions.dependencies import default_session_repository
from service.sessions.schemas import SessionCfg

session_states = default_session_repository.states

SID = 90001


@pytest.fixture()
def client():
    pairs = [
        PairResult(0, "filled", "rife", ["a", "m", "b"],
                   FrameQA("pass", "csq:pass", p_error=0.04, u=0.10), 0),
        PairResult(1, "needs_key", None, None, None, 1),
    ]
    session_states[SID] = {
        "result": CopilotResult(pairs=pairs, keys_requested_total=1, flagged=[],
                                n_autopass=1, n_corrected=0),
        "cfg": SessionCfg(engines="stub", cadence_fps=12, smoothness=2, show="Wistoria"),
        "explanations": {},
        "qa_degraded": False,
        "rev": 0,
    }
    app.state.feedback_store = InMemoryFeedbackStore()
    yield TestClient(app)
    session_states.pop(SID, None)
    app.state.feedback_store = None


def test_vote_then_list_roundtrip(client):
    r = client.post(f"/session/{SID}/feedback", json={"pair_index": 0, "vote": "down"})
    assert r.status_code == 200
    body = r.json()
    assert body["vote"] == "down" and body["voter"] == "anon"
    assert body["qa_status"] == "pass" and body["show"] == "Wistoria"

    listed = client.get(f"/session/{SID}/feedback").json()["feedback"]
    assert len(listed) == 1 and listed[0]["pair_index"] == 0


def test_revote_overwrites_not_duplicates(client):
    client.post(f"/session/{SID}/feedback", json={"pair_index": 0, "vote": "up"})
    client.post(f"/session/{SID}/feedback", json={"pair_index": 0, "vote": "down"})
    listed = client.get(f"/session/{SID}/feedback").json()["feedback"]
    assert len(listed) == 1 and listed[0]["vote"] == "down"


def test_needs_key_pair_is_422(client):
    r = client.post(f"/session/{SID}/feedback", json={"pair_index": 1, "vote": "down"})
    assert r.status_code == 422 and "needs_key" in r.json()["detail"]


def test_unknown_sid_is_404_and_bad_vote_is_422(client):
    assert client.post("/session/424242/feedback",
                       json={"pair_index": 0, "vote": "up"}).status_code == 404
    assert client.post(f"/session/{SID}/feedback",
                       json={"pair_index": 0, "vote": "meh"}).status_code == 422


def test_store_outage_is_503_not_500(client):
    class DeadStore:
        def upsert(self, record):
            raise RuntimeError("dynamo down")

        def list_session(self, sid):
            raise RuntimeError("dynamo down")

    app.state.feedback_store = DeadStore()
    r = client.post(f"/session/{SID}/feedback", json={"pair_index": 0, "vote": "up"})
    assert r.status_code == 503
