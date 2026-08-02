"""Reopening a saved session must hand back a WORKING session, not a museum.

Before this, a `pid` from History could only be read: the runtime `sid` that owns
`keys`/`eng`/`cfg`/`result` lives in one process, is capped at 8 and dies with a
restart, and nothing converted a durable `pid` back into one. The artist reloaded
the page, clicked their own session and got `This saved session is read-only.`

Resume restores the INPUTS and the RECORDED DECISIONS and regenerates nothing —
re-running would call the VLM again and could contradict the verdicts already on
the artist's screen.
"""
from __future__ import annotations

import io
import json
import time

import boto3
import numpy as np
import pytest
from PIL import Image

pytest.importorskip("fastapi")
from fastapi.testclient import TestClient
from moto import mock_aws

from service.app import app
from service.core.auth import CognitoJwtVerifier
from service.session_history.adapters import (
    DynamoSessionCatalog,
    DynamoTranscriptStore,
    S3ArtifactStore,
)
from service.sessions.dependencies import default_session_repository


ORIGIN = "https://testserver"
ISSUER = "https://cognito-idp.ap-southeast-1.amazonaws.com/pool-1"
BUCKET = "copilot-resume-test"
TABLE = "copilot_sessions"


def _png(value: int, size: int = 16) -> io.BytesIO:
    buffer = io.BytesIO()
    Image.fromarray(np.full((size, size, 3), value, np.uint8)).save(buffer, "PNG")
    buffer.seek(0)
    return buffer


def _files(count: int = 3):
    """Near-static keys, one grey level apart.

    stub_engines gates on `mean|diff| / 100` against tau_gate 0.017, so a bigger
    step makes every pair `needs_key` — a session with no filled pair cannot
    carry an artist verdict, and these tests would then pass while exercising
    nothing.
    """
    return [("keys", (f"{i}.png", _png(100 + i), "image/png")) for i in range(count)]


def _login(sub: str) -> TestClient:
    client = TestClient(app, base_url=ORIGIN)
    assert client.post(
        "/auth/session",
        headers={"Authorization": f"Bearer {sub}", "Origin": ORIGIN},
    ).status_code == 204
    return client


def _table(dynamodb):
    return dynamodb.create_table(
        TableName=TABLE,
        BillingMode="PAY_PER_REQUEST",
        AttributeDefinitions=[
            {"AttributeName": "pid", "AttributeType": "S"},
            {"AttributeName": "owner_sub", "AttributeType": "S"},
            {"AttributeName": "owner_sort", "AttributeType": "S"},
        ],
        KeySchema=[{"AttributeName": "pid", "KeyType": "HASH"}],
        GlobalSecondaryIndexes=[{
            "IndexName": "OwnerSessionsIndex",
            "KeySchema": [
                {"AttributeName": "owner_sub", "KeyType": "HASH"},
                {"AttributeName": "owner_sort", "KeyType": "RANGE"},
            ],
            "Projection": {"ProjectionType": "ALL"},
        }],
    )


@pytest.fixture
def published_runtime(monkeypatch):
    """A real /session run whose artifacts land in moto S3 + DynamoDB."""
    monkeypatch.setenv("COPILOT_AUTH_REQUIRED", "1")
    monkeypatch.setenv("COPILOT_FEEDBACK_BACKEND", "memory")
    monkeypatch.setenv("COPILOT_MEMORY_BACKEND", "memory")
    monkeypatch.setenv("AWS_PUBLISH", "1")
    monkeypatch.setenv("AWS_ARTIFACT_BUCKET", BUCKET)
    monkeypatch.setenv("AWS_SESSIONS_TABLE", TABLE)
    monkeypatch.setenv("AWS_REGION", "us-east-1")
    monkeypatch.setenv("AWS_DEFAULT_REGION", "us-east-1")
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "testing")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "testing")

    def decode(token: str) -> dict:
        return {"iss": ISSUER, "sub": token, "token_use": "id",
                "aud": "client-1", "exp": time.time() + 300}

    saved = {name: getattr(app.state, name, None) for name in (
        "auth_verifier", "session_catalog", "history_artifacts",
        "history_transcripts", "active_workspaces")}
    app.state.auth_verifier = CognitoJwtVerifier(
        "ap-southeast-1", "pool-1", "client-1", decoder=decode)
    # The per-owner active workspace is a separate recovery layer; keep it out so
    # this exercises the durable history path only.
    app.state.active_workspaces = None
    with mock_aws():
        dynamodb = boto3.resource("dynamodb", region_name="us-east-1")
        table = _table(dynamodb)
        s3 = boto3.client("s3", region_name="us-east-1")
        s3.create_bucket(Bucket=BUCKET)
        app.state.session_catalog = DynamoSessionCatalog(table)
        app.state.history_artifacts = S3ArtifactStore(s3, bucket=BUCKET)
        app.state.history_transcripts = DynamoTranscriptStore(
            table, app.state.history_artifacts)
        yield table, s3
    for name, old in saved.items():
        if old is None:
            try:
                delattr(app.state, name)
            except AttributeError:
                pass
        else:
            setattr(app.state, name, old)


def _run(client: TestClient, count: int = 3) -> tuple[int, str, dict]:
    """Run one real session; return (sid, pid, result event)."""
    response = client.post("/session", files=_files(count),
                           data={"engines": "stub"},
                           headers={"Origin": ORIGIN})
    assert response.status_code == 200, response.text
    result = published = None
    for block in response.text.split("\n\n"):
        if block.startswith("event: result"):
            result = json.loads(block.split("data: ", 1)[1])
        elif block.startswith("event: publish"):
            published = json.loads(block.split("data: ", 1)[1])
    assert result is not None, response.text
    assert published and published.get("pid"), response.text
    return result["sid"], published["pid"], result


def _forget(sid: int) -> None:
    """Simulate the restart/eviction that makes the live session unreachable."""
    default_session_repository.states.pop(sid, None)
    default_session_repository.paths.pop(sid, None)
    default_session_repository.owners.pop(sid, None)


def test_resume_rebuilds_a_working_session_from_the_durable_snapshot(published_runtime):
    owner = _login("user-a")
    sid, pid, result = _run(owner)
    original_pairs = [
        (pair["index"], pair["action"], pair["qa"])
        for pair in _pairs_of(owner, pid)
    ]
    _forget(sid)
    assert owner.post(f"/session/{sid}/agent", json={"message": "hi"},
                      headers={"Origin": ORIGIN}).status_code == 404

    response = owner.post(f"/session/resume/{pid}", headers={"Origin": ORIGIN})
    assert response.status_code == 200, response.text
    new_sid = response.json()["sid"]
    assert new_sid != sid

    state = default_session_repository.state_for(new_sid)
    assert state is not None
    # the source keys came back as real pixels, not placeholders
    assert len(state["keys"]) == 3
    assert all(isinstance(key, np.ndarray) and key.shape == (16, 16, 3)
               for key in state["keys"])
    # and the recorded decisions are unchanged, pair for pair
    assert [(pair.index, pair.action.value if hasattr(pair.action, "value") else pair.action,
             pair.qa.status.value if pair.qa is not None else None)
            for pair in state["result"].pairs] == original_pairs
    assert state["published_pid"] == pid


def _pairs_of(client: TestClient, pid: str) -> list[dict]:
    workspace = client.get(f"/sessions/{pid}/workspace")
    assert workspace.status_code == 200, workspace.text
    return workspace.json()["pairs"]


def test_a_resumed_session_answers_the_routes_that_404d_before(published_runtime):
    """The point of resume: the workbench stops being read-only.

    Each route is checked BEFORE resume too. Without that, a route that 404s for
    an unrelated reason — or one whose name I guessed wrong and that really
    405s — would let this pass while proving nothing.
    """
    owner = _login("user-a")
    sid, pid, _ = _run(owner)
    _forget(sid)
    dead = {
        "feedback": owner.get(f"/session/{sid}/feedback").status_code,
        "agent": owner.post(f"/session/{sid}/agent", json={"message": "hi"},
                            headers={"Origin": ORIGIN}).status_code,
        "verdicts": owner.post(
            f"/session/{sid}/feedback/batch",
            json={"verdicts": [{"pair_index": 0, "verdict": "accept"}]},
            headers={"Origin": ORIGIN}).status_code,
    }
    assert dead == {"feedback": 404, "agent": 404, "verdicts": 404}, dead

    new_sid = owner.post(f"/session/resume/{pid}",
                         headers={"Origin": ORIGIN}).json()["sid"]
    alive = {
        "feedback": owner.get(f"/session/{new_sid}/feedback").status_code,
        "agent": owner.post(f"/session/{new_sid}/agent", json={"message": "hi"},
                            headers={"Origin": ORIGIN}).status_code,
        "verdicts": owner.post(
            f"/session/{new_sid}/feedback/batch",
            json={"verdicts": [{"pair_index": 0, "verdict": "accept"}]},
            headers={"Origin": ORIGIN}).status_code,
    }
    # The verdict route answers 422 here — the stub's pairs pass QA outright, so
    # none is awaiting a decision. That is the route reading the restored result,
    # which is precisely what "no longer read-only" means; 404 would not be.
    assert alive["feedback"] == 200, alive
    assert alive["agent"] != 404 and alive["agent"] < 500, alive
    assert alive["verdicts"] == 422, alive


def test_resume_refuses_another_owners_session(published_runtime):
    owner = _login("user-a")
    sid, pid, _ = _run(owner)
    _forget(sid)
    stranger = _login("user-b")
    assert stranger.post(f"/session/resume/{pid}",
                         headers={"Origin": ORIGIN}).status_code == 404


def test_resume_refuses_a_snapshot_with_no_stored_keys(published_runtime):
    """A session whose source keys were never uploaded cannot be resumed, and must
    say so with a 409 rather than resurrecting an empty session."""
    table, s3 = published_runtime
    owner = _login("user-a")
    sid, pid, _ = _run(owner)
    _forget(sid)
    item = table.get_item(Key={"pid": pid})["Item"]
    snapshot = json.loads(
        s3.get_object(Bucket=BUCKET, Key=item["snapshot_key"])["Body"].read())
    snapshot["result"]["key_urls"] = {}
    s3.put_object(Bucket=BUCKET, Key=item["snapshot_key"],
                  Body=json.dumps(snapshot).encode())

    response = owner.post(f"/session/resume/{pid}", headers={"Origin": ORIGIN})
    assert response.status_code == 409
    assert "key" in response.json()["detail"].lower()


def test_resume_carries_the_artists_recorded_verdict_and_correction(published_runtime):
    """A decision recorded in the snapshot must survive the reload.

    The stub's pairs all pass QA, so no verdict can be submitted over HTTP here;
    the snapshot is edited directly instead, which pins the rebuild itself: what
    the durable record says about a pair is what the resumed pair says.
    """
    table, s3 = published_runtime
    owner = _login("user-a")
    sid, pid, _ = _run(owner)
    _forget(sid)
    item = table.get_item(Key={"pid": pid})["Item"]
    snapshot = json.loads(
        s3.get_object(Bucket=BUCKET, Key=item["snapshot_key"])["Body"].read())
    snapshot["pairs"][0]["artist_verdict"] = "accept"
    snapshot["pairs"][0]["correction"] = {
        "status": "resolved", "keys_used": 1,
        "rounds": [{"action": "regenerate", "reason": "line broke at the wrist"}],
    }
    s3.put_object(Bucket=BUCKET, Key=item["snapshot_key"],
                  Body=json.dumps(snapshot).encode())

    new_sid = owner.post(f"/session/resume/{pid}",
                         headers={"Origin": ORIGIN}).json()["sid"]
    restored = default_session_repository.state_for(new_sid)["result"].pairs[0]
    assert restored.artist_verdict == "accept"
    # The trace comes back as an OBJECT: re-projecting a resumed session to pair
    # events reads `.status` and `.rounds[].action_kind`, and a bare dict would
    # raise AttributeError there rather than here.
    from service.sessions.schemas import PairEvent
    assert PairEvent.from_pair(restored).correction == {
        "status": "resolved", "keys_used": 1,
        "rounds": [{"action": "regenerate", "reason": "line broke at the wrist"}],
    }


def test_a_resumed_session_refuses_frame_repair_instead_of_crashing(published_runtime):
    """Resume does not regenerate frames, so the repair path has nothing to paint
    on. It must refuse in words, not raise a 500 the artist reads as an outage."""
    owner = _login("user-a")
    sid, pid, _ = _run(owner)
    _forget(sid)
    new_sid = owner.post(f"/session/resume/{pid}",
                         headers={"Origin": ORIGIN}).json()["sid"]

    response = owner.post(
        f"/session/{new_sid}/pair/0/repair",
        json={"masks": [{"frame": 1, "png": ""}]},
        headers={"Origin": ORIGIN},
    )
    assert response.status_code == 422, response.text
    detail = response.json()["detail"].lower()
    # Naming the real cause matters: "no generated frame" alone reads as
    # `needs_key`, and the artist would go drawing a key that is not missing.
    assert "reopen" in detail, detail


def test_submitting_a_key_lifts_the_resumed_restriction(published_runtime):
    """Re-running the pipeline fills in the frames resume left out, so the
    refusal above must not outlive the run that fixed it."""
    from service.review.service import ReviewSession
    from service.media.rendering import render_session_artifacts

    owner = _login("user-a")
    # A mixed cut: keys 100/160/161 gate pair 0 to needs_key (gap 0.60) and fill
    # pair 1 (gap 0.01). add_keys demands a key for EVERY needs-key pair, and the
    # assertion below needs a pair that actually generates frames.
    files = [("keys", (f"{i}.png", _png(value), "image/png"))
             for i, value in enumerate((100, 160, 161))]
    response = owner.post("/session", files=files, data={"engines": "stub"},
                          headers={"Origin": ORIGIN})
    assert response.status_code == 200, response.text
    published = json.loads(next(
        block for block in response.text.split("\n\n")
        if block.startswith("event: publish")).split("data: ", 1)[1])
    result = json.loads(next(
        block for block in response.text.split("\n\n")
        if block.startswith("event: result")).split("data: ", 1)[1])
    _forget(result["sid"])

    new_sid = owner.post(f"/session/resume/{published['pid']}",
                         headers={"Origin": ORIGIN}).json()["sid"]
    state = default_session_repository.state_for(new_sid)
    assert state["resumed"] is True
    assert all(not pair.frames for pair in state["result"].pairs)
    gaps = [pair.index for pair in state["result"].pairs
            if pair.action.value == "needs_key"]
    assert gaps, "fixture produced no needs-key pair, so nothing is being tested"

    review = ReviewSession(default_session_repository, render_session_artifacts)
    review.add_keys(new_sid, [(index, state["keys"][index]) for index in gaps])
    after = default_session_repository.state_for(new_sid)
    assert after["resumed"] is False
    assert any(pair.frames for pair in after["result"].pairs)
