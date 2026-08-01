"""Ports for durable session metadata and object retrieval."""
from __future__ import annotations

from typing import Protocol

from service.session_history.models import (
    PublishedSession,
    SessionPage,
    StoredArtifact,
    WorkspaceSnapshot,
)


class SessionCatalog(Protocol):
    def list_for_owner(
        self, owner_sub: str, *, limit: int, cursor: str | None
    ) -> SessionPage: ...

    def get_owned(self, pid: str, owner_sub: str) -> PublishedSession | None: ...

    def create_for_owner(self, owner_sub: str, *, title: str) -> PublishedSession: ...

    def rename_owned(
        self, pid: str, owner_sub: str, *, title: str
    ) -> PublishedSession | None: ...

    def begin_delete_complete_owned(
        self, pid: str, owner_sub: str
    ) -> PublishedSession | None: ...

    def restore_delete_complete_owned(self, pid: str, owner_sub: str) -> None: ...

    def finish_delete_complete_owned(self, pid: str, owner_sub: str) -> None: ...


class ArtifactStore(Protocol):
    def get(self, key: str, *, filename: str) -> StoredArtifact | None: ...

    def get_workspace(self, key: str) -> WorkspaceSnapshot | None: ...

    def delete_prefix(self, prefix: str) -> None: ...
