"""Cognito JWT authentication for Stage 3.

The static site remains public so the SPA can render its own login/signup pages.
When ``COPILOT_AUTH_REQUIRED=1``, every ``/session*`` request must carry a valid
User-Pool ID or access token.  ``/me/*`` routes always require a token.
"""
from __future__ import annotations

from dataclasses import dataclass
import os
import time
from typing import Callable

from fastapi import HTTPException, Request


class AuthConfigurationError(RuntimeError):
    """Raised when production auth is enabled without complete Cognito config."""


@dataclass(frozen=True)
class CurrentUser:
    sub: str
    username: str | None
    claims: dict


def auth_required() -> bool:
    return os.environ.get("COPILOT_AUTH_REQUIRED", "").strip().lower() in {
        "1", "true", "yes", "on",
    }


class CognitoJwtVerifier:
    """Verify Cognito User-Pool JWTs and return the stable User-Pool ``sub``.

    ``decoder`` is an injection seam for unit tests.  The production decoder uses
    PyJWT's PyJWKClient, which caches Cognito's signing keys and verifies RS256.
    """

    def __init__(self, region: str, user_pool_id: str, app_client_id: str,
                 *, decoder: Callable[[str], dict] | None = None,
                 now: Callable[[], float] = time.time):
        if not region or not user_pool_id or not app_client_id:
            raise AuthConfigurationError(
                "Cognito auth needs region, user-pool id, and app-client id")
        self.region = region
        self.user_pool_id = user_pool_id
        self.app_client_id = app_client_id
        self.issuer = f"https://cognito-idp.{region}.amazonaws.com/{user_pool_id}"
        self.jwks_url = self.issuer + "/.well-known/jwks.json"
        self._decoder = decoder
        self._now = now
        self._jwk_client = None

    @classmethod
    def from_env(cls) -> "CognitoJwtVerifier":
        return cls(
            os.environ.get("COPILOT_COGNITO_REGION", ""),
            os.environ.get("COPILOT_COGNITO_USER_POOL_ID", ""),
            os.environ.get("COPILOT_COGNITO_APP_CLIENT_ID", ""),
        )

    def _decode_signed(self, token: str) -> dict:
        try:
            import jwt
        except ImportError as exc:  # pragma: no cover - deployment packaging guard
            raise AuthConfigurationError("PyJWT[crypto] is required for Cognito auth") from exc

        if self._jwk_client is None:
            self._jwk_client = jwt.PyJWKClient(self.jwks_url)
        key = self._jwk_client.get_signing_key_from_jwt(token).key
        # Cognito access tokens use client_id instead of aud.  Signature, issuer,
        # expiry and algorithm are still verified here; audience/client binding is
        # checked uniformly in _validate_claims below.
        return jwt.decode(
            token,
            key,
            algorithms=["RS256"],
            issuer=self.issuer,
            options={"verify_aud": False, "require": ["exp", "iss", "sub", "token_use"]},
        )

    def _validate_claims(self, claims: dict) -> CurrentUser:
        if claims.get("iss") != self.issuer:
            raise ValueError("wrong Cognito issuer")
        if float(claims.get("exp", 0)) <= self._now():
            raise ValueError("expired Cognito token")
        token_use = claims.get("token_use")
        if token_use == "id":
            if claims.get("aud") != self.app_client_id:
                raise ValueError("ID token is for another app client")
        elif token_use == "access":
            if claims.get("client_id") != self.app_client_id:
                raise ValueError("access token is for another app client")
        else:
            raise ValueError("token_use must be id or access")
        sub = str(claims.get("sub") or "").strip()
        if not sub:
            raise ValueError("Cognito token has no subject")
        username = claims.get("cognito:username") or claims.get("username") or claims.get("email")
        return CurrentUser(sub=sub, username=str(username) if username else None,
                           claims=dict(claims))

    def verify(self, token: str) -> CurrentUser:
        claims = (self._decoder or self._decode_signed)(token)
        return self._validate_claims(claims)


def _bearer_token(request: Request) -> str:
    scheme, _, token = request.headers.get("Authorization", "").partition(" ")
    if scheme.lower() != "bearer" or not token.strip():
        raise HTTPException(
            status_code=401,
            detail="Bearer token required",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return token.strip()


def verifier_for(request: Request) -> CognitoJwtVerifier:
    verifier = getattr(request.app.state, "auth_verifier", None)
    if verifier is not None:
        return verifier
    try:
        verifier = CognitoJwtVerifier.from_env()
    except AuthConfigurationError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    request.app.state.auth_verifier = verifier
    return verifier


def authenticate_request(request: Request) -> CurrentUser:
    try:
        token = _bearer_token(request)
        return verifier_for(request).verify(token)
    except HTTPException:
        raise
    except AuthConfigurationError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=401,
            detail="Invalid or expired Cognito token",
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc


def require_current_user(request: Request) -> CurrentUser:
    user = getattr(request.state, "user", None)
    if user is None:
        user = authenticate_request(request)
        request.state.user = user
    return user
