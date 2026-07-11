"""Stage-3 Cognito JWT authentication tests."""
import time
from types import SimpleNamespace

from fastapi.testclient import TestClient
import jwt
from cryptography.hazmat.primitives.asymmetric import rsa

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


def _signed_token(private_key, *, kid="key-1", **patch):
    claims = _claims(**patch)
    return jwt.encode(claims, private_key, algorithm="RS256", headers={"kid": kid})


class _RotatingJwks:
    def __init__(self, keys):
        self.keys = keys
        self.seen = []

    def get_signing_key_from_jwt(self, token):
        kid = jwt.get_unverified_header(token)["kid"]
        self.seen.append(kid)
        return SimpleNamespace(key=self.keys[kid])


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
    try:
        verifier.verify(tampered)
        assert False, "tampered Cognito token was accepted"
    except jwt.InvalidSignatureError:
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


def test_invalid_token_is_401_not_logged_and_options_does_not_require_auth(monkeypatch, caplog):
    monkeypatch.setenv("COPILOT_AUTH_REQUIRED", "1")

    class RejectingVerifier:
        def verify(self, token):
            raise ValueError("bad signature")

    old = getattr(app.state, "auth_verifier", None)
    app.state.auth_verifier = RejectingVerifier()
    secret_token = "header.payload.secret-signature"
    try:
        c = TestClient(app)
        r = c.post("/session/999/agent", json={"message": "hi"},
                   headers={"Authorization": "Bearer " + secret_token})
        assert r.status_code == 401
        assert secret_token not in caplog.text
        # CORS/preflight is allowed through the auth layer; route handling may
        # still answer 405 until Phong's deployment CORS policy supplies headers.
        assert c.options("/session").status_code != 401
    finally:
        if old is None:
            del app.state.auth_verifier
        else:
            app.state.auth_verifier = old
