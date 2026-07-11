"""Stage-3 Cognito JWT authentication tests."""
import time

from fastapi.testclient import TestClient

from service.app import app
from service.auth import CognitoJwtVerifier


ISSUER = "https://cognito-idp.ap-southeast-1.amazonaws.com/pool-1"


def _claims(**patch):
    claims = {
        "iss": ISSUER,
        "sub": "user-sub-1",
        "token_use": "access",
        "client_id": "client-1",
        "exp": time.time() + 300,
        "username": "artist@example.com",
    }
    claims.update(patch)
    return claims


def _verifier(claims):
    return CognitoJwtVerifier(
        "ap-southeast-1", "pool-1", "client-1",
        decoder=lambda token: claims,
    )


def test_accepts_access_and_id_token_client_binding():
    access = _verifier(_claims()).verify("signed")
    assert access.sub == "user-sub-1"
    assert access.username == "artist@example.com"

    id_user = _verifier(_claims(token_use="id", aud="client-1", client_id=None)).verify("signed")
    assert id_user.sub == access.sub


def test_rejects_wrong_client_expiry_issuer_and_token_use():
    bad = [
        _claims(client_id="other"),
        _claims(exp=1),
        _claims(iss="https://attacker.example/pool"),
        _claims(token_use="refresh"),
    ]
    for claims in bad:
        try:
            _verifier(claims).verify("signed")
            assert False, claims
        except ValueError:
            pass


def test_session_gate_is_off_for_local_development(monkeypatch):
    monkeypatch.delenv("COPILOT_AUTH_REQUIRED", raising=False)
    c = TestClient(app)
    assert c.post("/session/999999/agent", json={"message": "hi"}).status_code == 404


def test_session_gate_requires_bearer_when_enabled(monkeypatch):
    monkeypatch.setenv("COPILOT_AUTH_REQUIRED", "1")
    c = TestClient(app)
    r = c.post("/session/999999/agent", json={"message": "hi"})
    assert r.status_code == 401
    assert r.headers["www-authenticate"] == "Bearer"


def test_session_gate_accepts_injected_verified_user(monkeypatch):
    monkeypatch.setenv("COPILOT_AUTH_REQUIRED", "1")
    old = getattr(app.state, "auth_verifier", None)
    app.state.auth_verifier = _verifier(_claims())
    try:
        c = TestClient(app)
        r = c.post(
            "/session/999999/agent",
            json={"message": "hi"},
            headers={"Authorization": "Bearer signed"},
        )
        assert r.status_code == 404  # auth passed; route handled the request
    finally:
        if old is None:
            del app.state.auth_verifier
        else:
            app.state.auth_verifier = old
