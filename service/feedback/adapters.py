"""In-memory and DynamoDB adapters for the feedback persistence port."""
from __future__ import annotations

from decimal import Decimal
import threading

from service.feedback.models import FeedbackRecord


_FLOAT_FIELDS = ("p_error", "u")


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
            return sorted(
                (record.model_copy(deep=True) for record in rows),
                key=lambda record: (record.pair_index, record.voter),
            )


class DynamoFeedbackStore:
    """DynamoDB adapter keyed by session, pair index, and verified voter."""

    def __init__(self, table=None, *, table_name: str | None = None,
                 region: str | None = None):
        if table is None:
            import boto3
            if not table_name:
                raise RuntimeError("table_name is required for DynamoDB feedback")
            table = boto3.resource(
                "dynamodb",
                region_name=region,
            ).Table(table_name)
        self.table = table

    @staticmethod
    def _pk(sid: int) -> str:
        return f"SESSION#{sid}"

    @staticmethod
    def _sk(pair_index: int, voter: str) -> str:
        return f"PAIR#{pair_index}#VOTER#{voter}"

    @staticmethod
    def _from_row(row: dict) -> FeedbackRecord:
        document = {
            key: value for key, value in row.items()
            if key not in {"sessionPk", "feedbackSk"}
        }
        for field in _FLOAT_FIELDS:
            if isinstance(document.get(field), Decimal):
                document[field] = float(document[field])
        return FeedbackRecord.model_validate(document)

    def upsert(self, record: FeedbackRecord) -> FeedbackRecord:
        row = record.model_dump(mode="json")
        for field in _FLOAT_FIELDS:
            if row.get(field) is not None:
                row[field] = Decimal(str(row[field]))
        row.update(
            sessionPk=self._pk(record.sid),
            feedbackSk=self._sk(record.pair_index, record.voter),
        )
        self.table.put_item(Item=row)
        return record

    def list_session(self, sid: int) -> list[FeedbackRecord]:
        from boto3.dynamodb.conditions import Key
        response = self.table.query(
            KeyConditionExpression=Key("sessionPk").eq(self._pk(sid))
            & Key("feedbackSk").begins_with("PAIR#")
        )
        rows = [self._from_row(row) for row in response.get("Items", [])]
        return sorted(rows, key=lambda record: (record.pair_index, record.voter))
