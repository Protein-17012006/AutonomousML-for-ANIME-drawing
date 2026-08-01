"""A run by a signed-in artist must leave behind something resumable.

Without this, the four routes exist and every one of them truthfully reports
`{"workspace": null}` forever, because nothing ever opens a workspace. The
run's SSE is in-process and dies with the connection; these tests are what
make it durable.
"""
import io
import time

import numpy as np
import pytest
from PIL import Image

pytest.importorskip("fastapi")
from fastapi.testclient import TestClient

from service.active_workspace.dependencies import configure_active_workspace
from service.active_workspace.store import InMemoryActiveWorkspaceStore
from service.app import app
from service.core.auth import CognitoJwtVerifier


ISSUER = "https://cognito-idp.ap-southeast-1.amazonaws.com/pool-1"
ORIGIN = "https://testserver"


def _png(v: int) -> io.BytesIO:
    buffer = io.BytesIO()
    Image.fromarray(np.full((8, 8, 3), v, np.uint8)).save(buffer, "PNG")
    buffer.seek(0)
    return buffer


def _files():
    return [("keys", (f"{i}.png", _png(i * 60), "image/png")) for i in range(2)]


@pytest.fixture
def token_is_sub_verifier():
    def decode(token: str) -> dict:
        return {"iss": ISSUER, "sub": token, "token_use": "id",
                "aud": "client-1", "exp": time.time() + 300}

    old = getattr(app.state, "auth_verifier", None)
    app.state.auth_verifier = CognitoJwtVerifier(
        "ap-southeast-1", "pool-1", "client-1", decoder=decode)
    yield
    if old is None:
        del app.state.auth_verifier
    else:
        app.state.auth_verifier = old


@pytest.fixture
def workspaces():
    old = getattr(app.state, "active_workspace", None)
    configure_active_workspace(app, store=InMemoryActiveWorkspaceStore(),
                               publisher=lambda workspace: "pid-x")
    yield app.state.active_workspace
    if old is not None:
        app.state.active_workspace = old


def _login(sub: str) -> TestClient:
    client = TestClient(app, base_url=ORIGIN)
    assert client.post("/auth/session",
                       headers={"Authorization": f"Bearer {sub}",
                                "Origin": ORIGIN}).status_code == 204
    return client


def _run(client: TestClient) -> None:
    response = client.post("/session", files=_files(), data={"engines": "stub"},
                           headers={"Origin": ORIGIN})
    assert response.status_code == 200 and "event: result" in response.text


def test_a_signed_in_run_opens_a_workspace(monkeypatch, token_is_sub_verifier,
                                           workspaces):
    monkeypatch.setenv("COPILOT_AUTH_REQUIRED", "1")
    monkeypatch.setenv("COPILOT_FEEDBACK_BACKEND", "memory")
    _run(_login("user-a"))
    assert workspaces.active_for("user-a") is not None


def test_the_runs_pair_and_result_events_are_recorded_durably(
        monkeypatch, token_is_sub_verifier, workspaces):
    """The same events the SSE carried, kept so a reload can replay them."""
    monkeypatch.setenv("COPILOT_AUTH_REQUIRED", "1")
    monkeypatch.setenv("COPILOT_FEEDBACK_BACKEND", "memory")
    _run(_login("user-a"))

    workspace = workspaces.active_for("user-a")
    names = [event.name for event in
             workspaces.events_after(workspace.workspace_id, "user-a", after=0)]
    assert "pair" in names and "result" in names


def test_a_finished_run_leaves_a_resumable_snapshot(
        monkeypatch, token_is_sub_verifier, workspaces):
    """`snapshot` is what a resume rehydrates from, and its presence is also the
    test for "is there anything worth keeping" when a new run supersedes it."""
    monkeypatch.setenv("COPILOT_AUTH_REQUIRED", "1")
    monkeypatch.setenv("COPILOT_FEEDBACK_BACKEND", "memory")
    _run(_login("user-a"))

    workspace = workspaces.active_for("user-a")
    assert workspace.snapshot is not None
    assert workspace.revision >= 1


def test_an_anonymous_run_opens_no_workspace(monkeypatch, workspaces):
    """Local dev has no Cognito sub. A workspace with no owner could be handed
    to whoever asked next, so there must not be one."""
    monkeypatch.setenv("COPILOT_FEEDBACK_BACKEND", "memory")
    client = TestClient(app, base_url=ORIGIN)
    response = client.post("/session", files=_files(), data={"engines": "stub"},
                           headers={"Origin": ORIGIN})
    assert response.status_code == 200
    assert workspaces.active_for("") is None
    assert workspaces.active_for(None) is None


def test_the_runs_own_publication_is_recorded_on_the_workspace(
        monkeypatch, token_is_sub_verifier, workspaces):
    """The pid comes from `publish_session` — the thing that actually creates
    it — not from a second publisher invented for the workspace. The client
    reads `published_pid` to open the saved session, and listens for the
    `publish` event on the stream to close it."""
    import service.composition.session_runtime as composition_mod

    monkeypatch.setenv("COPILOT_AUTH_REQUIRED", "1")
    monkeypatch.setenv("COPILOT_FEEDBACK_BACKEND", "memory")
    monkeypatch.setattr(
        composition_mod, "publish_session",
        lambda sid, sdir, outcome, *, owner_sub=None, pid=None,
        workspace_input=None: {"published": True, "pid": "pid-9",
                               "s3_keys": [], "error": None})
    old_runtime = app.state.session_http_runtime
    app.state.session_http_runtime = composition_mod.build_session_http_runtime()
    try:
        _run(_login("user-a"))
        workspace = workspaces.active_for("user-a")
        assert workspace.published_pid == "pid-9"
        assert workspace.state == "published"
        recorded = [(event.name, event.data) for event in
                    workspaces.events_after(workspace.workspace_id, "user-a", after=0)]
        assert ("publish", {"published": True, "pid": "pid-9"}) in recorded
    finally:
        app.state.session_http_runtime = old_runtime


def test_a_run_whose_publication_fails_stays_retryable(
        monkeypatch, token_is_sub_verifier, workspaces):
    """publish_session never raises; it reports. A failed publication must leave
    the artist a workspace to finish saving, not a silently lost run."""
    import service.composition.session_runtime as composition_mod

    monkeypatch.setenv("COPILOT_AUTH_REQUIRED", "1")
    monkeypatch.setenv("COPILOT_FEEDBACK_BACKEND", "memory")
    monkeypatch.setattr(
        composition_mod, "publish_session",
        lambda sid, sdir, outcome, *, owner_sub=None, pid=None,
        workspace_input=None: {"published": False, "pid": None, "s3_keys": [],
                               "error": "S3 write failed"})
    old_runtime = app.state.session_http_runtime
    app.state.session_http_runtime = composition_mod.build_session_http_runtime()
    try:
        _run(_login("user-a"))
        workspace = workspaces.active_for("user-a")
        assert workspace.published_pid is None
        assert workspace.state == "publish_pending"
    finally:
        app.state.session_http_runtime = old_runtime
