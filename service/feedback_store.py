"""Flag-feedback stores: deterministic in-memory dev/test and DynamoDB prod.

Mirrors service/memory_store.py. Keying (sid, pair_index, voter) makes a
revote a plain overwrite: PK sessionPk = SESSION#{sid}, SK feedbackSk =
PAIR#{index}#VOTER#{voter}."""
from __future__ import annotations

from decimal import Decimal
import os
import threading
from typing import Protocol

from service.feedback import FeedbackRecord

_FLOAT_FIELDS = ("p_error", "u")


class FeedbackStore(Protocol):
    def upsert(self, record: FeedbackRecord) -> FeedbackRecord: ...
    def list_session(self, sid: int) -> list[FeedbackRecord]: ...


class InMemoryFeedbackStore:
    def __init__(self):
        self._data: dict[int, dict[tuple, FeedbackRecord]] = {}
        self._lock = threading.RLock()

    def upsert(self, record: FeedbackRecord) -> FeedbackRecord:
        with self._lock:
            bucket = self._data.setdefault(record.sid, {})
            bucket[(record.pair_index, record.voter)] = record.model_copy(deep=True)
            return record.model_copy(deep=True)

    def list_session(self, sid: int) -> list[FeedbackRecord]:
        with self._lock:
            rows = self._data.get(sid, {}).values()
            return sorted((r.model_copy(deep=True) for r in rows),
                          key=lambda r: (r.pair_index, r.voter))


class DynamoFeedbackStore:
    """DynamoDB adapter. Table schema: ``sessionPk`` (partition), ``feedbackSk``
    (sort). Server-owned like the memory table — NOT exposed through the
    browser Identity-Pool role (Stage-3 handoff rule)."""

    def __init__(self, table=None, *, table_name: str | None = None,
                 region: str | None = None):
        if table is None:
            import boto3
            name = table_name or os.environ.get("COPILOT_FEEDBACK_TABLE", "")
            if not name:
                raise RuntimeError("COPILOT_FEEDBACK_TABLE is required for DynamoDB feedback")
            table = boto3.resource(
                "dynamodb", region_name=region or os.environ.get("COPILOT_COGNITO_REGION")
            ).Table(name)
        self.table = table

    @staticmethod
    def _pk(sid: int) -> str:
        return f"SESSION#{sid}"

    @staticmethod
    def _sk(pair_index: int, voter: str) -> str:
        return f"PAIR#{pair_index}#VOTER#{voter}"

    @staticmethod
    def _from_row(row: dict) -> FeedbackRecord:
        doc = {k: v for k, v in row.items() if k not in {"sessionPk", "feedbackSk"}}
        for f in _FLOAT_FIELDS:
            if isinstance(doc.get(f), Decimal):
                doc[f] = float(doc[f])
        return FeedbackRecord.model_validate(doc)

    def upsert(self, record: FeedbackRecord) -> FeedbackRecord:
        row = record.model_dump(mode="json")
        for f in _FLOAT_FIELDS:
            if row.get(f) is not None:
                row[f] = Decimal(str(row[f]))
        row.update(sessionPk=self._pk(record.sid),
                   feedbackSk=self._sk(record.pair_index, record.voter))
        self.table.put_item(Item=row)
        return record

    def list_session(self, sid: int) -> list[FeedbackRecord]:
        from boto3.dynamodb.conditions import Key
        response = self.table.query(
            KeyConditionExpression=Key("sessionPk").eq(self._pk(sid))
                                   & Key("feedbackSk").begins_with("PAIR#")
        )
        rows = [self._from_row(r) for r in response.get("Items", [])]
        return sorted(rows, key=lambda r: (r.pair_index, r.voter))


def feedback_store_for(app) -> FeedbackStore:
    store = getattr(app.state, "feedback_store", None)
    if store is not None:
        return store
    from service.auth import auth_required
    default_backend = "dynamodb" if auth_required() else "memory"
    backend = os.environ.get("COPILOT_FEEDBACK_BACKEND", default_backend).strip().lower()
    if backend not in {"memory", "dynamodb"}:
        raise RuntimeError("COPILOT_FEEDBACK_BACKEND must be memory or dynamodb")
    store = DynamoFeedbackStore() if backend == "dynamodb" else InMemoryFeedbackStore()
    app.state.feedback_store = store
    return store
