"""FastAPI service for the in-between co-pilot.

POST /session   — multipart: field `keys` (one or more PNG files) + form field
                  `engines` (default "stub").  Returns SSE stream:
                    event: pair    (one per PairResult, in index order)
                    event: result  (final summary + artifact URLs)

GET /session/{sid}/{name} — download a session artifact.
"""
from __future__ import annotations

import os

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from service.assistant import api as assistant_routes
from service.core.dependencies import session_repository_for
from service.feedback import api as feedback_routes
from service.media import api as demo_routes
from service.memory import api as memory_routes
from service.review import api as review_routes
from service.sessions import api as session_routes

app = FastAPI(title="In-Between Co-pilot Service")
app.state.session_repository = session_repository_for()


@app.middleware("http")
async def _cognito_session_gate(request: Request, call_next):
    """Single-login Stage-3 gate.

    The SPA/login assets stay public.  Production can require the same Cognito
    bearer token on every GPU/session route without re-introducing ALB's second
    interactive login.  The flag defaults off for local stub development.
    """
    from service.core.auth import auth_required, authenticate_request

    has_bearer = request.headers.get("Authorization", "").lower().startswith("bearer ")
    if ((auth_required() or has_bearer) and request.method != "OPTIONS"
            and request.url.path.startswith("/session")):
        try:
            request.state.user = authenticate_request(request)
        except Exception as exc:
            from fastapi import HTTPException
            if isinstance(exc, HTTPException):
                return JSONResponse(
                    status_code=exc.status_code,
                    content={"detail": exc.detail},
                    headers=exc.headers,
                )
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


# Order matters: /session/planted/cases must register before GET /session/{sid}/{name}
# (an int-typed {sid} 422s on "planted" instead of falling through), the feedback
# router must too (GET /session/{sid}/feedback would be swallowed by the artifact
# route as name="feedback"), and the static mount must come last so API routes
# take precedence.
app.include_router(feedback_routes.router)
app.include_router(session_routes.router)
app.include_router(demo_routes.router)
app.include_router(assistant_routes.router)
app.include_router(review_routes.router)
app.include_router(memory_routes.router)


# --- static web UI: mounted LAST so the API routes above take precedence ---
from fastapi.staticfiles import StaticFiles  # noqa: E402

# Default = the vanilla web/ (always present → tests + dev fallback). Set
# COPILOT_WEB_DIR (relative to the repo root, or absolute) to serve a built
# frontend instead — the box launches with COPILOT_WEB_DIR=dist, where dist is the
# TEAM's canonical Next.js static export (in the export repo, deployed separately;
# this repo no longer carries a frontend build).
_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_WEB_DIR = os.environ.get("COPILOT_WEB_DIR") or "web"
if not os.path.isabs(_WEB_DIR):
    _WEB_DIR = os.path.join(_ROOT, _WEB_DIR)
if os.path.isdir(_WEB_DIR):
    app.mount("/", StaticFiles(directory=_WEB_DIR, html=True), name="web")
