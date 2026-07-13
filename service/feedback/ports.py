"""Persistence port for human flag feedback."""
from __future__ import annotations

from typing import Protocol

from service.feedback.models import FeedbackRecord


class FeedbackStore(Protocol):
    def upsert(self, record: FeedbackRecord) -> FeedbackRecord: ...
    def list_session(self, sid: int) -> list[FeedbackRecord]: ...
