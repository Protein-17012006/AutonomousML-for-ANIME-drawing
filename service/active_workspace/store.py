"""In-memory ActiveWorkspaceStore.

Not only a test double: it is also what a single-box deployment without DynamoDB
runs on, which is why it enforces ownership rather than trusting its caller.
"""
from __future__ import annotations

import threading

from service.active_workspace.models import ActiveWorkspace


class InMemoryActiveWorkspaceStore:
    def __init__(self) -> None:
        self._by_id: dict[str, ActiveWorkspace] = {}
        self._active: dict[str, str] = {}       # owner_sub -> workspace_id
        self._lock = threading.RLock()

    def active_for(self, owner_sub: str) -> ActiveWorkspace | None:
        with self._lock:
            workspace_id = self._active.get(owner_sub)
            if workspace_id is None:
                return None
            return self._by_id.get(workspace_id)

    def get_owned(self, workspace_id: str, owner_sub: str) -> ActiveWorkspace | None:
        with self._lock:
            workspace = self._by_id.get(workspace_id)
            # Ownership is checked HERE rather than in the route, so a caller
            # that forgets cannot leak another artist's run.
            if workspace is None or workspace.owner_sub != owner_sub:
                return None
            return workspace

    def save(self, workspace: ActiveWorkspace) -> None:
        with self._lock:
            self._by_id[workspace.workspace_id] = workspace

    def delete(self, workspace_id: str, owner_sub: str) -> None:
        with self._lock:
            workspace = self._by_id.get(workspace_id)
            if workspace is None or workspace.owner_sub != owner_sub:
                return
            self._by_id.pop(workspace_id, None)
            if self._active.get(owner_sub) == workspace_id:
                self._active.pop(owner_sub, None)

    def set_active(self, owner_sub: str, workspace_id: str | None) -> None:
        with self._lock:
            if workspace_id is None:
                self._active.pop(owner_sub, None)
            else:
                self._active[owner_sub] = workspace_id


class InMemoryWorkspaceAssetStore:
    """Uploaded inputs held in the process. Same caveat as the workspace store:
    fine for a single box, gone at the next restart."""

    def __init__(self) -> None:
        self._blobs: dict[tuple[str, str], tuple[bytes, str]] = {}

    def put(self, workspace_id: str, name: str, body: bytes,
            content_type: str) -> None:
        self._blobs[(workspace_id, name)] = (bytes(body), content_type)

    def get(self, workspace_id: str, name: str) -> tuple[bytes, str] | None:
        return self._blobs.get((workspace_id, name))
