"""Composition and FastAPI dependencies for the active workspace."""
from __future__ import annotations

from fastapi import Request

from service.active_workspace.service import ActiveWorkspaceService
from service.active_workspace.store import (
    InMemoryActiveWorkspaceStore,
    InMemoryWorkspaceAssetStore,
)


def _default_store():
    """DynamoDB when session history is configured, memory otherwise.

    The in-memory store is not a stub — a single-box deployment runs on it — but
    a workspace kept there dies with the process, so "resume after a reload"
    stops holding at the next restart. Wherever the durable table exists, use it.
    """
    from service.core.config import SessionHistorySettings

    try:
        settings = SessionHistorySettings.from_env()
    except Exception:                            # noqa: BLE001 — never block startup
        return InMemoryActiveWorkspaceStore()
    if not settings.enabled or not settings.table_name:
        return InMemoryActiveWorkspaceStore()
    try:
        import boto3

        from service.active_workspace.adapters import DynamoActiveWorkspaceStore

        table = boto3.resource(
            "dynamodb", region_name=settings.region).Table(settings.table_name)
        return DynamoActiveWorkspaceStore(table)
    except Exception:                            # noqa: BLE001 — degrade, don't crash
        return InMemoryActiveWorkspaceStore()


def _default_assets():
    """S3 when the artifact bucket is configured, memory otherwise — the same
    trade as `_default_store`, and it must move with it: a durable workspace
    whose assets vanished would hand a resume a URL with nothing behind it."""
    from service.core.config import SessionHistorySettings

    try:
        settings = SessionHistorySettings.from_env()
    except Exception:                            # noqa: BLE001 — never block startup
        return InMemoryWorkspaceAssetStore()
    if not settings.enabled or not settings.artifact_bucket:
        return InMemoryWorkspaceAssetStore()
    try:
        import boto3

        from service.active_workspace.adapters import S3WorkspaceAssetStore

        return S3WorkspaceAssetStore(
            boto3.client("s3", region_name=settings.region),
            bucket=settings.artifact_bucket)
    except Exception:                            # noqa: BLE001 — degrade, don't crash
        return InMemoryWorkspaceAssetStore()


def configure_active_workspace(app, *, store=None, publisher=None, assets=None,
                               max_idle_seconds: float = 300.0) -> None:
    app.state.active_workspace = ActiveWorkspaceService(
        store if store is not None else _default_store(),
        publisher=publisher,
        assets=assets if assets is not None else _default_assets())
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
