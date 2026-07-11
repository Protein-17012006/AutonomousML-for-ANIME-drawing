"""In-process session state, shared by the streaming worker and the follow-up routes.

sid -> temp dir path. BOUNDED (audit 2026-07-02): full-res numpy keys/frames were
retained forever on the long-lived box uvicorn — a slow leak. On overflow the oldest
session is evicted (temp dir rmtree'd, draw-key state dropped).
_state: retained run state for the draw-key loop (POST /key): sid -> {keys, eng, cfg,
result, rev, explanations, qa_degraded}. `explanations` (pair_index -> err_type/region/
explanation dict) and `qa_degraded` (bool) are snapshotted by the flag-feedback feature
(service/feedback.py) so a vote can carry the machine verdict that produced it.

sids seed from wall-clock epoch seconds (not a reset-to-1 counter): the DynamoDB
feedback/calibration table keys rows by `SESSION#{sid}`, so a counter that restarts at
1 on every boot would collide with — and silently overwrite — a prior boot's rows.
"""
import itertools
import os
import time

from service.session_store import BoundedSessionStore

_state: dict[int, dict] = {}
_sessions = BoundedSessionStore(
    cap=int(os.environ.get("COPILOT_MAX_SESSIONS", "8")), state=_state)
_sid_counter = itertools.count(int(time.time()))
