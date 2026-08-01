"""FastAPI service for the in-between co-pilot.

POST /session   — multipart: field `keys` (one or more PNG files) + form field
                  `engines` (default "stub").  Returns SSE stream:
                    event: pair    (one per PairResult, in index order)
                    event: result  (final summary + artifact URLs)

GET /session/{sid}/{name} — download a session artifact.
"""
from __future__ import annotations

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from service.assistant import api as assistant_routes
from service import auth_api
from service.composition.image_edit_runtime import build_image_edit_http_runtime
from service.composition.session_runtime import (
    build_review_http_runtime,
    build_session_http_runtime,
)
from service.feedback import api as feedback_routes
from service.image_edit import api as image_edit_routes
from service.media import api as demo_routes
from service.memory import api as memory_routes
from service.orchestration import api as orchestration_routes
from service.review import api as review_routes
from service.session_history import api as session_history_routes
from service.session_history.dependencies import configure_session_history
from service.sessions import api as session_routes
from service.sessions.http_dependencies import session_repository_for
from service.core.config import AuthSettings, WebSettings

app = FastAPI(title="In-Between Co-pilot Service")
# Validate security flags/config at process startup; malformed production env
# must fail the launch rather than silently disabling authentication.
app.state.auth_settings = AuthSettings.from_env()
app.state.session_repository = session_repository_for()
app.state.session_http_runtime = build_session_http_runtime()
app.state.review_http_runtime = build_review_http_runtime()
app.state.image_edit_http_runtime = build_image_edit_http_runtime()
configure_session_history(app)


@app.middleware("http")
async def _cognito_session_gate(request: Request, call_next):
    """Single-login Stage-3 gate.

    The SPA/login assets and cookie bootstrap stay public. Production session
    routes use the server-issued Cognito ID-token cookie. The flag defaults off
    for local stub development.
    """
    from service.core.auth import (alb_oidc_enabled, auth_cookie_name,
                                   auth_cookie_secure, auth_required, authenticate_request,
                                   authorize_session_access,
                                   validate_same_origin)

    path = request.url.path
    protected_route = (
        path == "/auth/me"
        or path == "/session" or path.startswith("/session/")
        or path == "/demo" or path.startswith("/demo/")
        or path == "/tools" or path.startswith("/tools/")
    )
    has_cookie = bool(request.cookies.get(auth_cookie_name()))
    has_trusted_alb_claims = (
        alb_oidc_enabled() and bool(request.headers.get("x-amzn-oidc-data", "").strip())
    )
    if ((auth_required() or has_cookie or has_trusted_alb_claims)
            and request.method != "OPTIONS"
            and protected_route):
        try:
            request.state.user = authenticate_request(request)
            if has_cookie:
                validate_same_origin(request)
        except Exception as exc:
            from fastapi import HTTPException
            if isinstance(exc, HTTPException):
                response = JSONResponse(
                    status_code=exc.status_code,
                    content={"detail": exc.detail},
                    headers=exc.headers,
                )
                if has_cookie and exc.status_code == 401:
                    response.delete_cookie(
                        auth_cookie_name(), path="/", secure=auth_cookie_secure(),
                        httponly=True, samesite="lax")
                return response
            raise

    # Session ownership: a session created by a verified Cognito user is invisible
    # to everyone else — same 404 wording as an unknown sid so strangers cannot
    # even confirm it exists. Enforced here (not per-route) so every current and
    # future /session/{sid}/* route inherits the isolation.
    segments = path.strip("/").split("/")
    sid = None
    if len(segments) >= 2 and segments[0] == "session":
        try:
            sid = int(segments[1])
        except ValueError:
            pass
    if request.method != "OPTIONS" and sid is not None:
        try:
            authorize_session_access(
                request, session_repository_for(request.app), sid)
        except Exception as exc:
            from fastapi import HTTPException
            if isinstance(exc, HTTPException):
                return JSONResponse(status_code=exc.status_code,
                                    content={"detail": exc.detail},
                                    headers=exc.headers)
            raise
    return await call_next(request)


@app.middleware("http")
async def _no_cache_html(request, call_next):
    """Never let index.html be served stale: a soft reload that reuses a cached index.html
    keeps pointing at a PRE-DEPLOY asset hash, so the user sees an old build (the recurring
    'I deployed but it's still wrong' trap — e.g. an old CSS layout after a fix). The hashed
    JS/CSS bundles are content-addressed/immutable, so they stay cacheable; only the HTML
    entry point is marked no-cache so a plain reload always picks up the latest assets."""
    response = await call_next(request)
    path = request.url.path
    if path == "/" or path.endswith(".html"):
        response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
    return response


# Order matters: the feedback router must register before GET /session/{sid}/{name}
# (GET /session/{sid}/feedback would be swallowed by the artifact route as
# name="feedback"), and the static mount must come last so API routes take precedence.
app.include_router(auth_api.router)
app.include_router(session_history_routes.router)
app.include_router(feedback_routes.router)
app.include_router(session_routes.router)
app.include_router(demo_routes.router)
app.include_router(assistant_routes.router)
app.include_router(orchestration_routes.router)
app.include_router(review_routes.router)
app.include_router(memory_routes.router)
app.include_router(image_edit_routes.router)


# --- static web UI: mounted LAST so the API routes above take precedence ---
from fastapi.staticfiles import StaticFiles  # noqa: E402

# Default = the vanilla web/ (always present → tests + dev fallback). Set
# COPILOT_WEB_DIR (relative to the repo root, or absolute) to serve a built
# frontend instead — the box launches with COPILOT_WEB_DIR=dist, where dist is the
# TEAM's canonical Next.js static export (in the export repo, deployed separately;
# this repo no longer carries a frontend build).
_WEB_DIR = WebSettings.from_env().directory
if _WEB_DIR.is_dir():
    app.mount("/", StaticFiles(directory=str(_WEB_DIR), html=True), name="web")
