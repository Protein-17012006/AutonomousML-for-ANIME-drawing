"""The four HTTP routes the deployed frontend already calls and gets 404 for.

The 401-vs-404 contrast is the whole point of the first test. Probed live on
2026-08-01, `/sessions` and `/session/1/agent` answered 401 (they exist, gated)
while all four `/active-workspace*` answered 404 (they do not exist). A user
reaching that part of the UI got a dead feature, not a permissions message.
"""
from __future__ import annotations

import json
import time

from fastapi.testclient import TestClient
import pytest

from service.active_workspace.dependencies import configure_active_workspace
from service.active_workspace.store import InMemoryActiveWorkspaceStore
from service.auth_dev_app import app
from service.core.auth import CognitoJwtVerifier
from service.session_history.models import WorkspaceSnapshot, WorkspaceUpload
from service.sessions.schemas import PairEvent, ResultEvent


ORIGIN = "https://testserver"
ISSUER = "https://cognito-idp.ap-southeast-1.amazonaws.com/pool-1"


def _verifier():
    def decode(token: str) -> dict:
        return {"iss": ISSUER, "sub": token, "token_use": "id", "aud": "client-1",
                "exp": time.time() + 300, "username": token}

    return CognitoJwtVerifier("ap-southeast-1", "pool-1", "client-1", decoder=decode)


def _login(sub: str) -> TestClient:
    client = TestClient(app, base_url=ORIGIN)
    response = client.post("/auth/session",
                           headers={"Authorization": f"Bearer {sub}", "Origin": ORIGIN})
    assert response.status_code == 204
    return client


def _snapshot() -> WorkspaceSnapshot:
    return WorkspaceSnapshot(
        schema_version=1,
        upload=WorkspaceUpload(mode="frames", label="3 keyframes",
                               filenames=["0.png", "1.png", "2.png"]),
        pairs=[PairEvent(index=0, action="fill", qa="pass", keys_requested=0)],
        result=ResultEvent(n_autopass=1, n_corrected=0, keys_requested_total=0,
                           flagged=[], abstained=[], needs_key=[], artifacts={}),
    )


@pytest.fixture
def workspaces():
    """Wire an in-memory store + a publisher that always succeeds."""
    old_verifier = getattr(app.state, "auth_verifier", None)
    old_service = getattr(app.state, "active_workspace", None)
    app.state.auth_verifier = _verifier()
    configure_active_workspace(app, store=InMemoryActiveWorkspaceStore(),
                               publisher=lambda workspace: "pid-1",
                               max_idle_seconds=0.2)
    try:
        yield app.state.active_workspace
    finally:
        app.state.auth_verifier = old_verifier
        if old_service is None:
            delattr(app.state, "active_workspace")
        else:
            app.state.active_workspace = old_service


def _sse_events(text: str) -> list[dict]:
    """Parse an SSE body into {id, event, data} frames."""
    frames = []
    for block in text.split("\n\n"):
        frame = {}
        for line in block.splitlines():
            if line.startswith("id:"):
                frame["id"] = int(line[3:].strip())
            elif line.startswith("event:"):
                frame["event"] = line[6:].strip()
            elif line.startswith("data:"):
                frame["data"] = json.loads(line[5:].strip())
        if "event" in frame:
            frames.append(frame)
    return frames


# --- the defect itself ----------------------------------------------------------

def test_the_route_exists_and_is_auth_gated_rather_than_missing(workspaces):
    """401, not 404. This assertion IS the bug report: before this change all
    four answered 404 while every real-but-gated route answered 401."""
    client = TestClient(app, base_url=ORIGIN)
    assert client.get("/active-workspace").status_code == 401


def test_an_owner_with_no_run_gets_a_null_workspace(workspaces):
    client = _login("owner-1")
    response = client.get("/active-workspace", headers={"Origin": ORIGIN})
    assert response.status_code == 200
    assert response.json() == {"workspace": None}


def test_an_open_run_is_returned_with_the_fields_the_client_requires(workspaces):
    workspaces.open_workspace("owner-1", upload=_snapshot().upload)
    client = _login("owner-1")
    body = client.get("/active-workspace", headers={"Origin": ORIGIN}).json()
    workspace = body["workspace"]
    assert isinstance(workspace["workspace_id"], str)
    assert isinstance(workspace["state"], str)
    assert workspace["published_pid"] is None


def test_an_unconfigured_store_reports_no_workspace_rather_than_503():
    """The client wraps this call in a .catch that raises a red banner, so a 503
    would redden the screen on every login wherever DynamoDB is not configured.
    `{"workspace": null}` is also simply true: there is no active workspace."""
    old_verifier = getattr(app.state, "auth_verifier", None)
    old_service = getattr(app.state, "active_workspace", None)
    app.state.auth_verifier = _verifier()
    if hasattr(app.state, "active_workspace"):
        delattr(app.state, "active_workspace")
    try:
        client = _login("owner-1")
        response = client.get("/active-workspace", headers={"Origin": ORIGIN})
        assert response.status_code == 200
        assert response.json() == {"workspace": None}
    finally:
        app.state.auth_verifier = old_verifier
        if old_service is not None:
            app.state.active_workspace = old_service


# --- the stream -----------------------------------------------------------------

def test_the_stream_replays_only_events_after_the_cursor(workspaces):
    workspace = workspaces.open_workspace("owner-1", upload=_snapshot().upload)
    for index in range(3):
        workspaces.append_event(workspace.workspace_id, "owner-1", "pair",
                                {"index": index, "action": "fill"})
    client = _login("owner-1")
    response = client.get(
        f"/active-workspace/{workspace.workspace_id}/stream?after=1",
        headers={"Origin": ORIGIN})
    frames = [f for f in _sse_events(response.text) if f["event"] == "pair"]
    assert [f["id"] for f in frames] == [2, 3]


def test_every_stream_frame_carries_the_id_the_client_resumes_from(workspaces):
    """Without `id:` the browser leaves lastEventId empty, the client computes
    Number("") = 0, and every frame looks older than the cursor."""
    workspace = workspaces.open_workspace("owner-1", upload=_snapshot().upload)
    workspaces.append_event(workspace.workspace_id, "owner-1", "pair",
                            {"index": 0, "action": "fill"})
    client = _login("owner-1")
    response = client.get(
        f"/active-workspace/{workspace.workspace_id}/stream?after=0",
        headers={"Origin": ORIGIN})
    frames = _sse_events(response.text)
    assert frames and all(isinstance(frame.get("id"), int) for frame in frames)


def test_the_stream_of_another_owners_workspace_is_not_found(workspaces):
    workspace = workspaces.open_workspace("owner-1", upload=_snapshot().upload)
    client = _login("owner-2")
    response = client.get(
        f"/active-workspace/{workspace.workspace_id}/stream?after=0",
        headers={"Origin": ORIGIN})
    assert response.status_code == 404


# --- publish and discard --------------------------------------------------------

def test_publish_returns_the_published_flag_and_pid(workspaces):
    workspace = workspaces.open_workspace("owner-1", upload=_snapshot().upload)
    workspaces.record_snapshot(workspace.workspace_id, "owner-1", _snapshot())
    client = _login("owner-1")
    response = client.post(f"/active-workspace/{workspace.workspace_id}/publish",
                           headers={"Origin": ORIGIN})
    assert response.status_code == 200
    assert response.json() == {"published": True, "pid": "pid-1"}


def test_discard_removes_the_workspace(workspaces):
    workspace = workspaces.open_workspace("owner-1", upload=_snapshot().upload)
    client = _login("owner-1")
    assert client.delete(f"/active-workspace/{workspace.workspace_id}",
                         headers={"Origin": ORIGIN}).status_code == 204
    assert client.get("/active-workspace",
                      headers={"Origin": ORIGIN}).json() == {"workspace": None}


def test_another_owner_can_neither_publish_nor_discard(workspaces):
    workspace = workspaces.open_workspace("owner-1", upload=_snapshot().upload)
    intruder = _login("owner-2")
    assert intruder.post(f"/active-workspace/{workspace.workspace_id}/publish",
                         headers={"Origin": ORIGIN}).status_code == 404
    assert intruder.delete(f"/active-workspace/{workspace.workspace_id}",
                           headers={"Origin": ORIGIN}).status_code == 404
    assert workspaces.active_for("owner-1") is not None
