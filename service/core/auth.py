"""Core Cognito JWT authentication for Stage 3.

The static site remains public so the SPA can render its own login/signup pages.
When ``COPILOT_AUTH_REQUIRED=1``, every session/GPU request must carry a valid
User-Pool ID/access token or explicitly trusted, ALB-signed claims. ``/me/*``
routes always require one of those verified identities.
"""
from __future__ import annotations

from dataclasses import dataclass
import re
import time
from typing import Callable
from urllib.request import urlopen

from fastapi import HTTPException, Request

from service.core.config import AuthSettings


SESSION_NOT_FOUND_DETAIL = "Unknown session (or no result yet)"


class AuthConfigurationError(RuntimeError):
    """Raised when production auth is enabled without complete Cognito config."""


@dataclass(frozen=True)
class CurrentUser:
    sub: str
    username: str | None
    claims: dict


def auth_required() -> bool:
    return AuthSettings.from_env(validate_required=False).required


def alb_oidc_enabled() -> bool:
    """Whether signed ALB user-claim headers are an accepted identity source."""
    return AuthSettings.from_env(validate_required=False).trust_alb_oidc


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
        settings = AuthSettings.from_env(validate_required=False)
        return cls(
            settings.region or "",
            settings.user_pool_id or "",
            settings.app_client_id or "",
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


class AlbOidcVerifier:
    """Verify the ES256 ``x-amzn-oidc-data`` claims signed by one ALB.

    The token header is untrusted until its signature verifies.  Its values are
    checked before the key lookup as defense in depth: the signer, Cognito
    issuer/client, expiry and key-id shape must all match explicit
    deployment configuration.  ``key_fetcher`` is an offline unit-test seam.
    """

    _KID_RE = re.compile(r"^[A-Za-z0-9-]{1,128}$")
    _REGION_RE = re.compile(r"^[a-z]{2}(?:-gov)?-[a-z]+-\d$")

    def __init__(self, region: str, alb_arn: str, user_pool_id: str,
                 app_client_id: str,
                 *, key_fetcher: Callable[[str, str], object] | None = None,
                 now: Callable[[], float] = time.time):
        region = region.strip()
        alb_arn = alb_arn.strip()
        user_pool_id = user_pool_id.strip()
        app_client_id = app_client_id.strip()
        if (not self._REGION_RE.fullmatch(region) or not alb_arn
                or not user_pool_id or not app_client_id):
            raise AuthConfigurationError(
                "ALB OIDC auth needs a valid region, ALB ARN, user-pool id, "
                "and app-client id")
        if not alb_arn.startswith(f"arn:aws:elasticloadbalancing:{region}:"):
            raise AuthConfigurationError("ALB ARN does not match the configured region")
        self.region = region
        self.alb_arn = alb_arn
        self.app_client_id = app_client_id
        self.issuer = f"https://cognito-idp.{region}.amazonaws.com/{user_pool_id}"
        self._key_fetcher = key_fetcher or self._fetch_public_key
        self._now = now
        self._keys: dict[str, object] = {}

    @classmethod
    def from_env(cls) -> "AlbOidcVerifier":
        settings = AuthSettings.from_env(validate_required=False)
        return cls(
            settings.region or "",
            settings.alb_arn or "",
            settings.user_pool_id or "",
            settings.app_client_id or "",
        )

    @staticmethod
    def _fetch_public_key(region: str, kid: str) -> bytes:
        url = f"https://public-keys.auth.elb.{region}.amazonaws.com/{kid}"
        with urlopen(url, timeout=3) as response:  # noqa: S310 - fixed AWS host + safe kid
            key = response.read(16_385)
        if not key or len(key) > 16_384:
            raise ValueError("invalid ALB public key response")
        return key

    def _validated_header(self, token: str) -> dict:
        try:
            import jwt
        except ImportError as exc:  # pragma: no cover - deployment packaging guard
            raise AuthConfigurationError("PyJWT[crypto] is required for ALB auth") from exc
        header = jwt.get_unverified_header(token)
        kid = str(header.get("kid") or "")
        if header.get("alg") != "ES256":
            raise ValueError("ALB token must use ES256")
        if header.get("signer") != self.alb_arn:
            raise ValueError("ALB token has the wrong signer")
        if header.get("iss") != self.issuer:
            raise ValueError("ALB token has the wrong issuer")
        if header.get("client") != self.app_client_id:
            raise ValueError("ALB token is for another app client")
        if float(header.get("exp", 0)) <= self._now():
            raise ValueError("expired ALB token")
        if not self._KID_RE.fullmatch(kid):
            raise ValueError("invalid ALB key id")
        return header

    def verify(self, token: str) -> CurrentUser:
        header = self._validated_header(token)
        kid = header["kid"]
        key = self._keys.get(kid)
        if key is None:
            key = self._key_fetcher(self.region, kid)
            self._keys[kid] = key
        import jwt
        claims = jwt.decode(
            token, key, algorithms=["ES256"],
            options={"verify_aud": False, "verify_exp": False},
        )
        sub = str(claims.get("sub") or "").strip()
        if not sub:
            raise ValueError("ALB claims have no subject")
        username = claims.get("cognito:username") or claims.get("username") or claims.get("email")
        return CurrentUser(sub=sub, username=str(username) if username else None,
                           claims=dict(claims))


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


def alb_verifier_for(request: Request) -> AlbOidcVerifier:
    verifier = getattr(request.app.state, "alb_auth_verifier", None)
    if verifier is not None:
        return verifier
    try:
        verifier = AlbOidcVerifier.from_env()
    except AuthConfigurationError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    request.app.state.alb_auth_verifier = verifier
    return verifier


def authenticate_request(request: Request) -> CurrentUser:
    try:
        authorization = request.headers.get("Authorization", "")
        alb_token = request.headers.get("x-amzn-oidc-data", "").strip()
        bearer_user = None
        alb_user = None
        if authorization:
            bearer_token = _bearer_token(request)
            bearer_user = verifier_for(request).verify(bearer_token)
        if alb_token and alb_oidc_enabled():
            alb_user = alb_verifier_for(request).verify(alb_token)
        if bearer_user is not None and alb_user is not None:
            if bearer_user.sub != alb_user.sub:
                raise ValueError("identity sources disagree")
            return bearer_user
        if bearer_user is not None:
            return bearer_user
        if alb_user is not None:
            return alb_user
        # A raw ALB identity header and an untrusted/disabled ALB claims header
        # are deliberately not identity. Fall back to the standard 401 response.
        _bearer_token(request)
        raise AssertionError("unreachable")
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


def request_user_sub(request: Request) -> str | None:
    """Stable Cognito sub set by the auth middleware; None on the anonymous dev path."""
    return getattr(getattr(request.state, "user", None), "sub", None)


def authorize_session_access(request: Request, repository, sid: int) -> None:
    """Authorize one session reference without disclosing whether it exists.

    Ownerless sessions remain available only to the anonymous, auth-disabled
    local-development flow.  Once production auth is enabled (or a caller has
    presented an identity), an absent owner fails closed.  This also gives
    non-``/session/{sid}`` routes such as memory extraction the exact same
    tenant boundary as artifact/review/assistant routes.
    """
    owner = repository.owner_for(sid)
    caller = request_user_sub(request)
    if owner is None:
        if auth_required() or caller is not None:
            raise HTTPException(status_code=404, detail=SESSION_NOT_FOUND_DETAIL)
        return
    if caller != owner:
        raise HTTPException(status_code=404, detail=SESSION_NOT_FOUND_DETAIL)


def require_current_user(request: Request) -> CurrentUser:
    user = getattr(request.state, "user", None)
    if user is None:
        user = authenticate_request(request)
        request.state.user = user
    return user
