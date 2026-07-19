"""Stage-3 session-ownership isolation.

Phong's acceptance rule: two Cognito users must never see each other's session
data — if user 1's agent/DeepSeek can read user 2's session, auth failed. These
tests bind a session to the verified User-Pool ``sub`` that created it and make
every ``/session/{sid}/*`` access from anyone else a 404 (not 403: existence is
not confirmed to strangers). Sids must also be non-sequential so a session id
cannot be enumerated from one's own.
"""
import io
import time

import numpy as np
import pytest
from PIL import Image

pytest.importorskip("fastapi")
from fastapi.testclient import TestClient

from service.app import app
from service.core.auth import CognitoJwtVerifier
from service.sessions.dependencies import default_session_repository
from service.sessions.repository import InMemorySessionRepository

session_states = default_session_repository.states

ISSUER = "https://cognito-idp.ap-southeast-1.amazonaws.com/pool-1"


def _png(v: int) -> io.BytesIO:
    b = io.BytesIO()
    Image.fromarray(np.full((8, 8, 3), v, np.uint8)).save(b, "PNG")
    b.seek(0)
    return b


def _files():
    return [("keys", (f"{i}.png", _png(i * 60), "image/png")) for i in range(2)]


ORIGIN = "https://testserver"


def _login(sub: str) -> TestClient:
    client = TestClient(app, base_url=ORIGIN)
    response = client.post(
        "/auth/session",
        headers={"Authorization": f"Bearer {sub}", "Origin": ORIGIN},
    )
    assert response.status_code == 204
    return client


@pytest.fixture
def token_is_sub_verifier():
    """Inject a verifier whose decoder treats the bearer token AS the sub —
    each test mints distinct Cognito users by choosing token strings."""
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


def _create_session(client: TestClient) -> int:
    before = set(session_states)
    r = client.post("/session", files=_files(), data={"engines": "stub"},
                    headers={"Origin": ORIGIN})
    assert r.status_code == 200 and "event: result" in r.text
    new = set(session_states) - before
    assert new, "session did not register in the repository"
    return new.pop()


def test_two_users_cannot_read_each_others_sessions(monkeypatch, token_is_sub_verifier):
    monkeypatch.setenv("COPILOT_AUTH_REQUIRED", "1")
    # auth-on flips store defaults to DynamoDB; keep this test box-free
    monkeypatch.setenv("COPILOT_FEEDBACK_BACKEND", "memory")
    monkeypatch.setenv("COPILOT_MEMORY_BACKEND", "memory")
    owner = _login("user-a")
    stranger = _login("user-b")
    sid = _create_session(owner)

    # the owner keeps access; any other *valid* Cognito user gets 404
    assert owner.get(f"/session/{sid}/feedback").status_code == 200
    assert stranger.get(f"/session/{sid}/feedback").status_code == 404
    assert stranger.post(f"/session/{sid}/agent", json={"message": "hi"},
                         headers={"Origin": ORIGIN}).status_code == 404
    assert stranger.get(f"/session/{sid}/report.json").status_code == 404


def test_rerun_child_session_inherits_the_owner(monkeypatch, token_is_sub_verifier):
    # /session/{sid}/rerun mints a NEW sid — it must stay as private as its parent
    monkeypatch.setenv("COPILOT_AUTH_REQUIRED", "1")
    monkeypatch.setenv("COPILOT_FEEDBACK_BACKEND", "memory")
    monkeypatch.setenv("COPILOT_MEMORY_BACKEND", "memory")
    owner = _login("user-a")
    stranger = _login("user-b")
    parent = _create_session(owner)

    before = set(session_states)
    r = owner.post(f"/session/{parent}/rerun", headers={"Origin": ORIGIN})
    assert r.status_code == 200 and "event: result" in r.text
    child = (set(session_states) - before).pop()

    assert stranger.get(f"/session/{child}/feedback").status_code == 404
    assert owner.get(f"/session/{child}/feedback").status_code == 200


def test_owned_session_hidden_from_anonymous_even_in_dev(monkeypatch, token_is_sub_verifier):
    # auth flag OFF, but the creator presented a bearer token (local integration
    # mode): the session is owned, so an anonymous request must not read it.
    monkeypatch.delenv("COPILOT_AUTH_REQUIRED", raising=False)
    owner = _login("user-a")
    anonymous = TestClient(app, base_url=ORIGIN)
    sid = _create_session(owner)

    assert anonymous.get(f"/session/{sid}/feedback").status_code == 404
    assert owner.get(f"/session/{sid}/feedback").status_code == 200


def test_ownerless_sessions_stay_open_for_local_dev(monkeypatch):
    # no token anywhere (today's stub/dev flow) → behavior unchanged
    monkeypatch.delenv("COPILOT_AUTH_REQUIRED", raising=False)
    c = TestClient(app, base_url=ORIGIN)
    sid = _create_session(c)
    assert c.get(f"/session/{sid}/feedback").status_code == 200


def test_sids_are_not_sequential_or_js_unsafe():
    repo = InMemorySessionRepository(cap=2)
    a, _ = repo.create()
    b, _ = repo.create()
    assert b != a + 1, "sids must not be enumerable by incrementing"
    assert 0 < a < 2**53 and 0 < b < 2**53  # JSON/JS Number-safe


def test_history_pid_is_owned_and_reaches_publisher(monkeypatch, token_is_sub_verifier):
    import types
    import service.composition.session_runtime as composition_mod

    monkeypatch.setenv("COPILOT_AUTH_REQUIRED", "1")
    calls = []

    class Catalog:
        def get_owned(self, pid, owner_sub):
            if pid == "draft-pid" and owner_sub == "user-a":
                return types.SimpleNamespace(
                    summary=types.SimpleNamespace(status="draft")
                )
            return None

    monkeypatch.setattr(
        composition_mod,
        "publish_session",
        lambda sid, sdir, outcome, *, owner_sub=None, pid=None, workspace_input=None: calls.append(
            (owner_sub, pid, workspace_input)
        ),
    )
    old_runtime = app.state.session_http_runtime
    old_catalog = getattr(app.state, "session_catalog", None)
    app.state.session_http_runtime = composition_mod.build_session_http_runtime()
    app.state.session_catalog = Catalog()
    try:
        owner = _login("user-a")
        response = owner.post(
            "/session",
            files=_files(),
            data={"engines": "stub", "history_pid": "draft-pid"},
            headers={"Origin": ORIGIN},
        )
        assert response.status_code == 200
        assert calls == [("user-a", "draft-pid", {
            "mode": "frames", "label": "2 keyframes", "filenames": ["0.png", "1.png"]
        })]
        stranger = _login("user-b")
        assert stranger.post(
            "/session",
            files=_files(),
            data={"engines": "stub", "history_pid": "draft-pid"},
            headers={"Origin": ORIGIN},
        ).status_code == 404
    finally:
        app.state.session_http_runtime = old_runtime
        if old_catalog is None:
            delattr(app.state, "session_catalog")
        else:
            app.state.session_catalog = old_catalog
