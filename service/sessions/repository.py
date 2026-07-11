"""Session repository port and the current bounded in-process adapter."""
from __future__ import annotations

import itertools
import tempfile
import time
from typing import Protocol

from service.sessions.store import BoundedSessionStore


class SessionRepository(Protocol):
    def create(self, prefix: str = "copilot_session") -> tuple[int, str]: ...
    def register_path(self, sid: int, path: str) -> None: ...
    def path_for(self, sid: int) -> str | None: ...
    def state_for(self, sid: int) -> dict | None: ...
    def save_state(self, sid: int, state: dict) -> None: ...


class InMemorySessionRepository:
    """Single-process adapter preserving the existing bounded retention policy.

    Keeping this behind a port makes a Redis/Dynamo-backed implementation possible
    without allowing routes and use cases to depend on module-level dictionaries.
    """

    def __init__(self, cap: int = 8, *, id_source=None):
        self.states: dict[int, dict] = {}
        self.paths = BoundedSessionStore(cap=cap, state=self.states)
        self.id_source = id_source or itertools.count(int(time.time()))

    def create(self, prefix: str = "copilot_session") -> tuple[int, str]:
        sid = next(self.id_source)
        path = tempfile.mkdtemp(prefix=f"{prefix}_{sid}_")
        self.register_path(sid, path)
        return sid, path

    def register_path(self, sid: int, path: str) -> None:
        self.paths[sid] = path

    def path_for(self, sid: int) -> str | None:
        return self.paths.get(sid)

    def state_for(self, sid: int) -> dict | None:
        return self.states.get(sid)

    def save_state(self, sid: int, state: dict) -> None:
        if sid not in self.paths:
            raise KeyError(f"session {sid} has no registered artifact path")
        self.states[sid] = state
