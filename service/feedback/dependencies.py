"""Feedback adapter selection at the application composition boundary."""
from __future__ import annotations

from service.core.auth import auth_required
from service.core.config import feedback_store_settings
from service.feedback.adapters import DynamoFeedbackStore, InMemoryFeedbackStore
from service.feedback.ports import FeedbackStore


def feedback_store_for(app) -> FeedbackStore:
    store = getattr(app.state, "feedback_store", None)
    if store is not None:
        return store
    default_backend = "dynamodb" if auth_required() else "memory"
    settings = feedback_store_settings(default_backend)
    store = (
        DynamoFeedbackStore(
            table_name=settings.table_name,
            region=settings.region,
        )
        if settings.backend == "dynamodb"
        else InMemoryFeedbackStore()
    )
    app.state.feedback_store = store
    return store
