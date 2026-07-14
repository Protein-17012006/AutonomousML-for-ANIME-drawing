"""FastAPI dependencies and injected HTTP runtime for session-facing routes."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from fastapi import HTTPException, Request

from service.sessions.dependencies import default_session_repository
from service.sessions.repository import SessionRepository


@dataclass(frozen=True)
class SessionHttpRuntime:
    load_keys: Callable
    load_video_keys: Callable
    stream_session: Callable


def session_repository_for(app=None) -> SessionRepository:
    if app is not None:
        repository = getattr(app.state, "session_repository", None)
        if repository is not None:
            return repository
    return default_session_repository


def get_session_repository(request: Request) -> SessionRepository:
    return session_repository_for(request.app)


def get_session_http_runtime(request: Request) -> SessionHttpRuntime:
    runtime = getattr(request.app.state, "session_http_runtime", None)
    if runtime is None:
        raise HTTPException(status_code=503, detail="session runtime is not configured")
    return runtime
