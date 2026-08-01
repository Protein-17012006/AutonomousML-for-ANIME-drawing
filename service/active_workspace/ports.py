"""Port for durable active-workspace storage.

Mirrors service/session_history/ports.py: a Protocol the application depends on,
with a boto3 adapter in production and an in-memory one in tests.
"""
from __future__ import annotations

from typing import Protocol

from service.active_workspace.models import ActiveWorkspace


class ActiveWorkspaceStore(Protocol):
    def active_for(self, owner_sub: str) -> ActiveWorkspace | None: ...

    def get_owned(self, workspace_id: str, owner_sub: str) -> ActiveWorkspace | None: ...

    def save(self, workspace: ActiveWorkspace) -> None: ...

    def delete(self, workspace_id: str, owner_sub: str) -> None: ...

    def set_active(self, owner_sub: str, workspace_id: str | None) -> None: ...


class WorkspaceAssetStore(Protocol):
    """The artist's ORIGINAL uploads, kept so a resume on a machine whose
    IndexedDB is empty can rebuild the File objects it needs."""

    def put(self, workspace_id: str, name: str, body: bytes,
            content_type: str) -> None: ...

    def get(self, workspace_id: str, name: str) -> tuple[bytes, str] | None: ...
