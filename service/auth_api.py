"""Stateless Cognito ID-token cookie bootstrap and session endpoints."""
from __future__ import annotations

from datetime import datetime, timezone
import time

from fastapi import APIRouter, Depends, HTTPException, Request, Response

from service.core.auth import (
    CurrentUser,
    auth_cookie_name,
    auth_cookie_secure,
    authenticate_bearer_request,
    bearer_token,
    require_current_user,
    validate_same_origin,
)


router = APIRouter(prefix="/auth", tags=["auth"])


def _clear_cookie(response: Response) -> None:
    response.delete_cookie(
        key=auth_cookie_name(),
        path="/",
        secure=auth_cookie_secure(),
        httponly=True,
        samesite="lax",
    )


@router.post("/session", status_code=204)
def establish_session(request: Request, response: Response) -> None:
    user = authenticate_bearer_request(request)
    token = bearer_token(request)
    expires_at = float(user.claims["exp"])
    max_age = int(expires_at - time.time())
    if max_age <= 0:
        # The verifier normally catches this; keep the cookie boundary fail-closed.
        _clear_cookie(response)
        raise HTTPException(status_code=401, detail="Cognito ID token expired")
    response.set_cookie(
        key=auth_cookie_name(),
        value=token,
        max_age=max_age,
        expires=datetime.fromtimestamp(expires_at, tz=timezone.utc),
        path="/",
        secure=auth_cookie_secure(),
        httponly=True,
        samesite="lax",
    )
    response.headers["Cache-Control"] = "no-store"


@router.get("/me")
def get_me(user: CurrentUser = Depends(require_current_user)) -> dict:
    name = user.claims.get("name")
    return {
        "user_sub": user.sub,
        "username": user.username,
        "name": name if isinstance(name, str) else None,
        "expires_at": int(float(user.claims.get("exp", 0))),
    }


@router.post("/logout", status_code=204)
def logout(request: Request, response: Response) -> None:
    validate_same_origin(request)
    _clear_cookie(response)
    response.headers["Cache-Control"] = "no-store"
