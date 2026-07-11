"""Feedback adapter selection at the application composition boundary."""
from __future__ import annotations

import os

from service.core.auth import auth_required
from service.feedback.adapters import DynamoFeedbackStore, InMemoryFeedbackStore
from service.feedback.ports import FeedbackStore


def feedback_store_for(app) -> FeedbackStore:
    store = getattr(app.state, "feedback_store", None)
    if store is not None:
        return store
    default_backend = "dynamodb" if auth_required() else "memory"
    backend = os.environ.get("COPILOT_FEEDBACK_BACKEND", default_backend).strip().lower()
    if backend not in {"memory", "dynamodb"}:
        raise RuntimeError("COPILOT_FEEDBACK_BACKEND must be memory or dynamodb")
    store = DynamoFeedbackStore() if backend == "dynamodb" else InMemoryFeedbackStore()
    app.state.feedback_store = store
    return store
