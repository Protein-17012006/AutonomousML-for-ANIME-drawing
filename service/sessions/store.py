"""Bounded in-process session path store (audit fix 2026-07-02, finding #5).

The service previously kept every session's temp dir + full-resolution numpy
key/frame arrays forever on the long-lived box uvicorn — an unbounded leak
(slow OOM across demo days). This store caps retained sessions: on overflow the
OLDEST session is evicted — its temp dir rmtree'd and its draw-key state dropped.
Insertion order == recency because sids come from a monotonic counter; a plain
dict preserves insertion order (py3.7+), so no OrderedDict needed. Box-free by
design (stdlib only) so it unit-tests off-box, unlike service.app (fastapi).
"""
from __future__ import annotations

import shutil
import threading


class BoundedSessionStore(dict):
    """sid -> temp-dir path, capped. Evicts the oldest session on overflow,
    removing its temp dir and its entry in the companion `state` dict."""

    def __init__(self, cap: int = 8, state: dict | None = None):
        super().__init__()
        self.cap = max(1, int(cap))
        self.state = state if state is not None else {}
        self._pins: dict[object, int] = {}
        self._lock = threading.RLock()

    def __setitem__(self, sid, path):
        self.add(sid, path)

    def add(self, sid, path, *, pin: bool = False):
        """Register ``sid`` and optionally pin it before eviction runs.

        A session worker must use ``pin=True`` atomically with insertion.  A
        separate ``store[sid] = path; store.pin(sid)`` has a race where another
        request can evict the new session between those two operations.
        """
        with self._lock:
            super().__setitem__(sid, path)
            if pin:
                self._pins[sid] = self._pins.get(sid, 0) + 1
            self._evict_unpinned()

    def pin(self, sid) -> None:
        """Keep a registered session alive while an in-flight job uses it."""
        with self._lock:
            if not super().__contains__(sid):
                raise KeyError(f"unknown session {sid}")
            self._pins[sid] = self._pins.get(sid, 0) + 1

    def unpin(self, sid) -> None:
        """Release one lease and enforce the retention cap when it reaches zero."""
        with self._lock:
            count = self._pins.get(sid, 0)
            if count <= 1:
                self._pins.pop(sid, None)
            else:
                self._pins[sid] = count - 1
            self._evict_unpinned()

    def is_pinned(self, sid) -> bool:
        with self._lock:
            return self._pins.get(sid, 0) > 0

    def _evict_unpinned(self) -> None:
        while len(self) > self.cap:
            oldest = next(
                (candidate for candidate in super().__iter__()
                 if self._pins.get(candidate, 0) == 0),
                None,
            )
            # Temporary overflow is safer than deleting an in-flight session.
            # The next unpin immediately retries eviction.
            if oldest is None:
                return
            old_path = super().pop(oldest)
            self._pins.pop(oldest, None)
            self.state.pop(oldest, None)
            shutil.rmtree(old_path, ignore_errors=True)
