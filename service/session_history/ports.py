"""Ports for durable session metadata and object retrieval."""
from __future__ import annotations

from typing import Protocol

from service.session_history.models import PublishedSession, SessionPage, StoredArtifact


class SessionCatalog(Protocol):
    def list_for_owner(
        self, owner_sub: str, *, limit: int, cursor: str | None
    ) -> SessionPage: ...

    def get_owned(self, pid: str, owner_sub: str) -> PublishedSession | None: ...


class ArtifactStore(Protocol):
    def get(self, key: str, *, filename: str) -> StoredArtifact | None: ...
