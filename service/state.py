"""In-process session state, shared by the streaming worker and the follow-up routes.

sid -> temp dir path. BOUNDED (audit 2026-07-02): full-res numpy keys/frames were
retained forever on the long-lived box uvicorn — a slow leak. On overflow the oldest
session is evicted (temp dir rmtree'd, draw-key state dropped).
_state: retained run state for the draw-key loop (POST /key): sid -> {keys, eng, cfg, result, rev}
"""
import itertools
import os

from service.session_store import BoundedSessionStore

_state: dict[int, dict] = {}
_sessions = BoundedSessionStore(
    cap=int(os.environ.get("COPILOT_MAX_SESSIONS", "8")), state=_state)
_sid_counter = itertools.count(1)
