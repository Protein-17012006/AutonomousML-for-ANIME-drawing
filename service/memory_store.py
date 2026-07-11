"""Long-term-memory stores: deterministic in-memory dev/test and DynamoDB prod."""
from __future__ import annotations

from decimal import Decimal
import os
import threading
from typing import Protocol

from service.memory import MAX_MEMORIES_PER_USER, MemoryItem


class MemoryStore(Protocol):
    def list(self, user_sub: str) -> list[MemoryItem]: ...
    def put(self, user_sub: str, item: MemoryItem) -> MemoryItem: ...
    def get(self, user_sub: str, memory_id: str) -> MemoryItem | None: ...
    def delete(self, user_sub: str, memory_id: str) -> bool: ...


class InMemoryMemoryStore:
    def __init__(self):
        self._data: dict[str, dict[str, MemoryItem]] = {}
        self._lock = threading.RLock()

    def list(self, user_sub: str) -> list[MemoryItem]:
        with self._lock:
            rows = self._data.get(user_sub, {}).values()
            return sorted((m.model_copy(deep=True) for m in rows),
                          key=lambda m: m.updated_at, reverse=True)

    def put(self, user_sub: str, item: MemoryItem) -> MemoryItem:
        with self._lock:
            bucket = self._data.setdefault(user_sub, {})
            if item.id not in bucket and len(bucket) >= MAX_MEMORIES_PER_USER:
                raise ValueError(f"memory limit is {MAX_MEMORIES_PER_USER} per user")
            bucket[item.id] = item.model_copy(deep=True)
            return item.model_copy(deep=True)

    def get(self, user_sub: str, memory_id: str) -> MemoryItem | None:
        with self._lock:
            item = self._data.get(user_sub, {}).get(memory_id)
            return item.model_copy(deep=True) if item else None

    def delete(self, user_sub: str, memory_id: str) -> bool:
        with self._lock:
            return self._data.get(user_sub, {}).pop(memory_id, None) is not None


class DynamoMemoryStore:
    """DynamoDB adapter keyed by the verified User-Pool subject.

    Table schema: ``userPk`` (partition key), ``memorySk`` (sort key).  This is
    intentionally separate from Phong's Identity-Pool keyed conversation index.
    """

    def __init__(self, table=None, *, table_name: str | None = None,
                 region: str | None = None):
        if table is None:
            import boto3
            name = table_name or os.environ.get("COPILOT_MEMORY_TABLE", "")
            if not name:
                raise RuntimeError("COPILOT_MEMORY_TABLE is required for DynamoDB memory")
            table = boto3.resource(
                "dynamodb", region_name=region or os.environ.get("COPILOT_COGNITO_REGION")
            ).Table(name)
        self.table = table

    @staticmethod
    def _pk(user_sub: str) -> str:
        return "USER#" + user_sub

    @staticmethod
    def _sk(memory_id: str) -> str:
        return "MEMORY#" + memory_id

    @staticmethod
    def _from_row(row: dict) -> MemoryItem:
        doc = {k: v for k, v in row.items() if k not in {"userPk", "memorySk"}}
        if isinstance(doc.get("confidence"), Decimal):
            doc["confidence"] = float(doc["confidence"])
        return MemoryItem.model_validate(doc)

    def list(self, user_sub: str) -> list[MemoryItem]:
        from boto3.dynamodb.conditions import Key
        response = self.table.query(
            KeyConditionExpression=Key("userPk").eq(self._pk(user_sub))
                                   & Key("memorySk").begins_with("MEMORY#")
        )
        rows = [self._from_row(row) for row in response.get("Items", [])]
        return sorted(rows, key=lambda m: m.updated_at, reverse=True)

    def put(self, user_sub: str, item: MemoryItem) -> MemoryItem:
        if self.get(user_sub, item.id) is None and len(self.list(user_sub)) >= MAX_MEMORIES_PER_USER:
            raise ValueError(f"memory limit is {MAX_MEMORIES_PER_USER} per user")
        row = item.model_dump(mode="json")
        row.update(userPk=self._pk(user_sub), memorySk=self._sk(item.id))
        row["confidence"] = Decimal(str(row["confidence"]))
        self.table.put_item(Item=row)
        return item

    def get(self, user_sub: str, memory_id: str) -> MemoryItem | None:
        response = self.table.get_item(Key={
            "userPk": self._pk(user_sub), "memorySk": self._sk(memory_id),
        })
        row = response.get("Item")
        return self._from_row(row) if row else None

    def delete(self, user_sub: str, memory_id: str) -> bool:
        response = self.table.delete_item(
            Key={"userPk": self._pk(user_sub), "memorySk": self._sk(memory_id)},
            ReturnValues="ALL_OLD",
        )
        return bool(response.get("Attributes"))


def memory_store_for(app) -> MemoryStore:
    store = getattr(app.state, "memory_store", None)
    if store is not None:
        return store
    from service.auth import auth_required
    default_backend = "dynamodb" if auth_required() else "memory"
    backend = os.environ.get("COPILOT_MEMORY_BACKEND", default_backend).strip().lower()
    if backend not in {"memory", "dynamodb"}:
        raise RuntimeError("COPILOT_MEMORY_BACKEND must be memory or dynamodb")
    store = DynamoMemoryStore() if backend == "dynamodb" else InMemoryMemoryStore()
    app.state.memory_store = store
    return store
