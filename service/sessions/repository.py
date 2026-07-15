"""Session repository port and the current bounded in-process adapter."""
from __future__ import annotations

import secrets
import tempfile
import threading
from contextlib import contextmanager
from typing import ContextManager, Protocol

from service.sessions.store import BoundedSessionStore


def _random_sids():
    """Non-enumerable session ids, kept under 2**53 so they survive JSON/JS Number."""
    while True:
        yield secrets.randbits(53) or 1


class SessionRepository(Protocol):
    def create(self, prefix: str = "copilot_session", *, pin: bool = False) -> tuple[int, str]: ...
    def register_path(self, sid: int, path: str) -> None: ...
    def pin(self, sid: int) -> None: ...
    def unpin(self, sid: int) -> None: ...
    def session_transaction(self, sid: int) -> ContextManager[None]: ...
    def path_for(self, sid: int) -> str | None: ...
    def state_for(self, sid: int) -> dict | None: ...
    def save_state(self, sid: int, state: dict) -> None: ...
    def set_owner(self, sid: int, sub: str) -> None: ...
    def owner_for(self, sid: int) -> str | None: ...


class InMemorySessionRepository:
    """Single-process adapter preserving the existing bounded retention policy.

    Keeping this behind a port makes a Redis/Dynamo-backed implementation possible
    without allowing routes and use cases to depend on module-level dictionaries.
    """

    def __init__(self, cap: int = 8, *, id_source=None):
        self.states: dict[int, dict] = {}
        self.owners: dict[int, str] = {}
        self.paths = BoundedSessionStore(cap=cap, state=self.states)
        self.id_source = id_source or _random_sids()
        self._lock = threading.RLock()
        self._session_locks: dict[int, threading.RLock] = {}

    def create(self, prefix: str = "copilot_session", *, pin: bool = False) -> tuple[int, str]:
        with self._lock:
            sid = next(self.id_source)
            path = tempfile.mkdtemp(prefix=f"{prefix}_{sid}_")
            self.paths.add(sid, path, pin=pin)
            self._prune_owners()
            return sid, path

    def register_path(self, sid: int, path: str) -> None:
        with self._lock:
            self.paths[sid] = path
            self._prune_owners()

    def pin(self, sid: int) -> None:
        self.paths.pin(sid)

    def unpin(self, sid: int) -> None:
        with self._lock:
            self.paths.unpin(sid)
            self._prune_owners()

    @contextmanager
    def session_transaction(self, sid: int):
        """Serialize one session mutation and keep its artifacts alive."""
        with self._lock:
            self.paths.pin(sid)
            lock = self._session_locks.setdefault(sid, threading.RLock())
        try:
            with lock:
                yield
        finally:
            self.unpin(sid)

    def path_for(self, sid: int) -> str | None:
        with self._lock:
            return self.paths.get(sid)

    def state_for(self, sid: int) -> dict | None:
        with self._lock:
            return self.states.get(sid)

    def save_state(self, sid: int, state: dict) -> None:
        with self._lock:
            if sid not in self.paths:
                raise KeyError(f"session {sid} has no registered artifact path")
            self.states[sid] = state

    def set_owner(self, sid: int, sub: str) -> None:
        with self._lock:
            self._prune_owners()
            self.owners[sid] = sub

    def owner_for(self, sid: int) -> str | None:
        with self._lock:
            return self.owners.get(sid)

    def _prune_owners(self) -> None:
        # Keep the same dictionary object: callers/tests may retain a reference.
        for sid in tuple(self.owners):
            if sid not in self.paths:
                self.owners.pop(sid, None)
        for sid in tuple(self._session_locks):
            if sid not in self.paths:
                self._session_locks.pop(sid, None)
