"""Stateless Cognito ID-token cookie authentication tests."""
import time
from types import SimpleNamespace

from fastapi.testclient import TestClient
import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa

from service.app import app
from service.core.auth import CognitoJwtVerifier
from service.core.config import AuthSettings, ConfigurationError


ISSUER = "https://cognito-idp.ap-southeast-1.amazonaws.com/pool-1"
ORIGIN = "https://testserver"


def _claims(**patch):
    claims = {
        "iss": ISSUER,
        "sub": "user-sub-1",
        "token_use": "id",
        "aud": "client-1",
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


def _signed_token(private_key, *, kid="key-1", **patch):
    return jwt.encode(_claims(**patch), private_key, algorithm="RS256", headers={"kid": kid})


class _RotatingJwks:
    def __init__(self, keys):
        self.keys = keys
        self.seen = []

    def get_signing_key_from_jwt(self, token):
        kid = jwt.get_unverified_header(token)["kid"]
        self.seen.append(kid)
        return SimpleNamespace(key=self.keys[kid])


@pytest.fixture
def injected_verifier():
    old = getattr(app.state, "auth_verifier", None)
    app.state.auth_verifier = _verifier(_claims())
    yield
    if old is None:
        del app.state.auth_verifier
    else:
        app.state.auth_verifier = old


def _client():
    return TestClient(app, base_url=ORIGIN)


def _bootstrap(client: TestClient, token="signed"):
    return client.post(
        "/auth/session",
        headers={"Authorization": f"Bearer {token}", "Origin": ORIGIN},
    )


def test_accepts_id_token_and_rejects_access_token():
    user = _verifier(_claims()).verify("signed")
    assert user.sub == "user-sub-1"
    assert user.username == "artist@example.com"

    with pytest.raises(ValueError):
        _verifier(_claims(token_use="access", aud=None, client_id="client-1")).verify("signed")


def test_insecure_cookie_requires_explicit_local_override(monkeypatch):
    monkeypatch.setenv("COPILOT_AUTH_REQUIRED", "1")
    monkeypatch.setenv("COPILOT_AUTH_COOKIE_SECURE", "0")
    monkeypatch.setenv("COPILOT_COGNITO_REGION", "ap-southeast-1")
    monkeypatch.setenv("COPILOT_COGNITO_USER_POOL_ID", "pool-1")
    monkeypatch.setenv("COPILOT_COGNITO_APP_CLIENT_ID", "client-1")
    with pytest.raises(ConfigurationError):
        AuthSettings.from_env()
    monkeypatch.setenv("COPILOT_AUTH_ALLOW_INSECURE_COOKIE", "1")
    assert AuthSettings.from_env().cookie_secure is False


def test_rejects_wrong_client_expiry_issuer_token_use_and_future_nbf():
    bad = [
        _claims(aud="other"),
        _claims(exp=1),
        _claims(iss="https://attacker.example/pool"),
        _claims(token_use="refresh"),
        _claims(nbf=time.time() + 300),
        _claims(sub=""),
    ]
    for claims in bad:
        with pytest.raises(ValueError):
            _verifier(claims).verify("signed")


def test_real_rs256_signature_tamper_and_jwks_key_rotation():
    keys = {
        "key-1": rsa.generate_private_key(public_exponent=65537, key_size=2048),
        "key-2": rsa.generate_private_key(public_exponent=65537, key_size=2048),
    }
    jwks = _RotatingJwks({kid: key.public_key() for kid, key in keys.items()})
    verifier = CognitoJwtVerifier("ap-southeast-1", "pool-1", "client-1")
    verifier._jwk_client = jwks

    first = _signed_token(keys["key-1"], kid="key-1")
    second = _signed_token(keys["key-2"], kid="key-2", sub="user-sub-2")
    assert verifier.verify(first).sub == "user-sub-1"
    assert verifier.verify(second).sub == "user-sub-2"
    assert jwks.seen == ["key-1", "key-2"]

    head, payload, signature = first.split(".")
    tampered = ".".join((head, payload, ("A" if signature[0] != "A" else "B") + signature[1:]))
    with pytest.raises(jwt.InvalidSignatureError):
        verifier.verify(tampered)


def test_cookie_bootstrap_me_and_logout(monkeypatch, injected_verifier):
    monkeypatch.setenv("COPILOT_AUTH_REQUIRED", "1")
    client = _client()
    established = _bootstrap(client)
    assert established.status_code == 204
    cookie = established.headers["set-cookie"]
    assert "__Host-copilot_id=" in cookie
    assert "HttpOnly" in cookie
    assert "Secure" in cookie
    assert "SameSite=lax" in cookie
    assert "Path=/" in cookie

    me = client.get("/auth/me")
    assert me.status_code == 200
    assert me.json()["user_sub"] == "user-sub-1"
    assert me.json()["expires_at"] > time.time()

    logged_out = client.post("/auth/logout", headers={"Origin": ORIGIN})
    assert logged_out.status_code == 204
    assert "Max-Age=0" in logged_out.headers["set-cookie"]
    assert client.get("/auth/me").status_code == 401


def test_session_gate_requires_cookie_when_enabled(monkeypatch):
    monkeypatch.setenv("COPILOT_AUTH_REQUIRED", "1")
    response = _client().post(
        "/session/999999/agent",
        json={"message": "hi"},
        headers={"Origin": ORIGIN},
    )
    assert response.status_code == 401


def test_session_gate_stays_open_for_anonymous_local_stub(monkeypatch):
    monkeypatch.delenv("COPILOT_AUTH_REQUIRED", raising=False)
    response = _client().post("/session/999999/agent", json={"message": "hi"})
    assert response.status_code == 404


def test_session_gate_accepts_cookie_and_rejects_cross_site(monkeypatch, injected_verifier):
    monkeypatch.setenv("COPILOT_AUTH_REQUIRED", "1")
    client = _client()
    assert _bootstrap(client).status_code == 204
    accepted = client.post(
        "/session/999999/agent",
        json={"message": "hi"},
        headers={"Origin": ORIGIN},
    )
    assert accepted.status_code == 404
    rejected = client.post(
        "/session/999999/agent",
        json={"message": "hi"},
        headers={"Origin": "https://attacker.example", "Sec-Fetch-Site": "cross-site"},
    )
    assert rejected.status_code == 403


def test_invalid_bootstrap_token_is_401_not_logged(monkeypatch, caplog):
    monkeypatch.setenv("COPILOT_AUTH_REQUIRED", "1")

    class RejectingVerifier:
        def verify(self, token):
            raise ValueError("bad signature")

    old = getattr(app.state, "auth_verifier", None)
    app.state.auth_verifier = RejectingVerifier()
    secret_token = "header.payload.secret-signature"
    try:
        response = _bootstrap(_client(), secret_token)
        assert response.status_code == 401
        assert secret_token not in caplog.text
        assert _client().options("/session").status_code != 401
    finally:
        if old is None:
            del app.state.auth_verifier
        else:
            app.state.auth_verifier = old
