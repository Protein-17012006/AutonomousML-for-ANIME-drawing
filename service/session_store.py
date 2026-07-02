"""Bounded in-process session store (audit fix 2026-07-02, finding #5).

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


class BoundedSessionStore(dict):
    """sid -> temp-dir path, capped. Evicts the oldest session on overflow,
    removing its temp dir and its entry in the companion `state` dict."""

    def __init__(self, cap: int = 8, state: dict | None = None):
        super().__init__()
        self.cap = max(1, int(cap))
        self.state = state if state is not None else {}

    def __setitem__(self, sid, path):
        super().__setitem__(sid, path)
        while len(self) > self.cap:
            oldest = next(iter(self))
            old_path = super().pop(oldest)
            self.state.pop(oldest, None)
            shutil.rmtree(old_path, ignore_errors=True)
