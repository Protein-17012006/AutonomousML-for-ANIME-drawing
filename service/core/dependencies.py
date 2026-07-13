"""Application composition helpers and FastAPI dependency adapters."""
from __future__ import annotations

from fastapi import Request

from service.sessions.dependencies import default_session_repository
from service.sessions.repository import SessionRepository


def session_repository_for(app=None) -> SessionRepository:
    if app is not None:
        repository = getattr(app.state, "session_repository", None)
        if repository is not None:
            return repository
    return default_session_repository


def get_session_repository(request: Request) -> SessionRepository:
    """FastAPI dependency: make the route's session dependency explicit."""
    return session_repository_for(request.app)
