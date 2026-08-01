"""Composition and FastAPI dependencies for the active workspace."""
from __future__ import annotations

from fastapi import Request

from service.active_workspace.service import ActiveWorkspaceService
from service.active_workspace.store import InMemoryActiveWorkspaceStore


def configure_active_workspace(app, *, store=None, publisher=None,
                               max_idle_seconds: float = 300.0) -> None:
    app.state.active_workspace = ActiveWorkspaceService(
        store or InMemoryActiveWorkspaceStore(), publisher=publisher)
    # A stream is not immortal. The client reconnects 1s after onerror, so a
    # bounded lifetime costs a reconnect rather than a lost run, and it stops a
    # dropped connection pinning a worker forever.
    app.state.active_workspace_max_idle = max_idle_seconds


def get_active_workspace_service(request: Request) -> ActiveWorkspaceService | None:
    """None when unconfigured — deliberately NOT a 503.

    The route turns None into `{"workspace": null}`. The client wraps this call
    in a .catch that raises a red banner, so a 503 would redden the screen on
    every login in any environment without the store, to say something that is
    already true: there is no active workspace.
    """
    return getattr(request.app.state, "active_workspace", None)


def get_active_workspace_max_idle(request: Request) -> float:
    return float(getattr(request.app.state, "active_workspace_max_idle", 300.0))
