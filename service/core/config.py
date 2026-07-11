"""Environment-backed service settings.

Only this module knows the environment variable names used by the service.  The
rest of the application asks small functions for the value it needs, which keeps
configuration parsing out of feature and infrastructure modules.
"""
from __future__ import annotations

import os


def env_bool(name: str, default: bool = False) -> bool:
    value = os.environ.get(name)
    if value is None:
        return default
    return value.strip().lower() not in {"", "0", "false", "no", "off"}


def max_sessions() -> int:
    return max(1, int(os.environ.get("COPILOT_MAX_SESSIONS", "8")))


def sse_keepalive_seconds() -> float:
    return float(os.environ.get("COPILOT_SSE_KEEPALIVE", "15"))


def smoothness_x4_enabled() -> bool:
    return env_bool("COPILOT_SMOOTHNESS_X4")
