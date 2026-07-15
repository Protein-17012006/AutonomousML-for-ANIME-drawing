"""Memory adapter selection at the application composition boundary."""
from __future__ import annotations

from service.core.auth import auth_required
from service.core.config import memory_store_settings
from service.memory.adapters import DynamoMemoryStore, InMemoryMemoryStore
from service.memory.ports import MemoryStore


def memory_store_for(app) -> MemoryStore:
    store = getattr(app.state, "memory_store", None)
    if store is not None:
        return store
    default_backend = "dynamodb" if auth_required() else "memory"
    settings = memory_store_settings(default_backend)
    store = (
        DynamoMemoryStore(
            table_name=settings.table_name,
            region=settings.region,
        )
        if settings.backend == "dynamodb"
        else InMemoryMemoryStore()
    )
    app.state.memory_store = store
    return store
