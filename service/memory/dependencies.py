"""Memory adapter selection at the application composition boundary."""
from __future__ import annotations

import os

from service.core.auth import auth_required
from service.memory.adapters import DynamoMemoryStore, InMemoryMemoryStore
from service.memory.ports import MemoryStore


def memory_store_for(app) -> MemoryStore:
    store = getattr(app.state, "memory_store", None)
    if store is not None:
        return store
    default_backend = "dynamodb" if auth_required() else "memory"
    backend = os.environ.get("COPILOT_MEMORY_BACKEND", default_backend).strip().lower()
    if backend not in {"memory", "dynamodb"}:
        raise RuntimeError("COPILOT_MEMORY_BACKEND must be memory or dynamodb")
    store = DynamoMemoryStore() if backend == "dynamodb" else InMemoryMemoryStore()
    app.state.memory_store = store
    return store
