"""Boto3 adapters for the durable session table and artifact bucket."""
from __future__ import annotations

import base64
from datetime import datetime, timezone
from decimal import Decimal
import json
import pathlib
import time
import uuid

from pydantic import ValidationError

from service.session_history.models import (
    ArtifactLinks,
    PublishedSession,
    SessionPage,
    SessionSummary,
    SessionSummaryCounts,
    StoredArtifact,
    WorkspaceSnapshot,
)


_LINK_NAMES = {
    "montage.png": "montage",
    "report.md": "report",
    "reconstructed.mp4": "video",
    "compare.mp4": "compare",
}
_ALLOWED_SUFFIXES = {".png", ".md", ".mp4"}


class InvalidCursor(ValueError):
    pass


def _integer(value) -> int:
    if isinstance(value, Decimal):
        return int(value)
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def _json_list(value) -> list:
    if isinstance(value, list):
        return value
    if not isinstance(value, str):
        return []
    try:
        parsed = json.loads(value)
    except (TypeError, ValueError):
        return []
    return parsed if isinstance(parsed, list) else []


def _count_json_list(value) -> int:
    return len(_json_list(value))


def _created_at(timestamp: int) -> str:
    return datetime.fromtimestamp(timestamp, tz=timezone.utc).isoformat().replace(
        "+00:00", "Z"
    )


def _safe_snapshot_key(pid: str, value) -> str | None:
    expected = f"artifacts/{pid}/workspace.v1.json"
    return expected if value == expected else None


def _safe_artifact_keys(pid: str, value) -> dict[str, str]:
    prefix = f"artifacts/{pid}/"
    safe: dict[str, str] = {}
    for candidate in _json_list(value):
        if not isinstance(candidate, str) or not candidate.startswith(prefix):
            continue
        relative = candidate[len(prefix):]
        if not relative or "/" in relative or "\\" in relative:
            continue
        path = pathlib.PurePosixPath(relative)
        if path.name != relative or path.suffix.lower() not in _ALLOWED_SUFFIXES:
            continue
        safe[relative] = candidate
    return safe


def _summary_from_row(row: dict) -> PublishedSession | None:
    pid = str(row.get("pid") or "").strip()
    owner_sub = str(row.get("owner_sub") or "").strip()
    owner_sort = str(row.get("owner_sort") or "").strip()
    timestamp = _integer(row.get("ts"))
    if not pid or not owner_sub or not owner_sort or timestamp <= 0:
        return None
    artifact_keys = _safe_artifact_keys(pid, row.get("artifact_keys"))
    snapshot_version = _integer(row.get("snapshot_version")) or None
    snapshot_key = _safe_snapshot_key(pid, row.get("snapshot_key"))
    status = str(row.get("status") or "complete")
    if status not in {"draft", "complete"}:
        return None
    updated_at = max(timestamp, _integer(row.get("updated_at")))
    links: dict[str, str | None] = {
        "montage": None,
        "report": None,
        "video": None,
    }
    for basename in artifact_keys:
        field = _LINK_NAMES.get(basename)
        if field:
            links[field] = f"/sessions/{pid}/artifacts/{basename}"
    summary = SessionSummary(
        pid=pid,
        title=str(row.get("title") or "Untitled session").strip()[:80]
        or "Untitled session",
        status=status,
        created_at=_created_at(timestamp),
        updated_at=_created_at(updated_at),
        workspace_available=(
            status == "complete" and snapshot_version == 1 and snapshot_key is not None
        ),
        summary=SessionSummaryCounts(
            n_pairs=max(0, _integer(row.get("n_pairs"))),
            n_autopass=max(0, _integer(row.get("n_autopass"))),
            n_corrected=max(0, _integer(row.get("n_corrected"))),
            flagged=_count_json_list(row.get("flagged")),
            abstained=_count_json_list(row.get("abstained")),
            needs_key=_count_json_list(row.get("needs_key")),
        ),
        artifacts=ArtifactLinks(**links),
    )
    return PublishedSession(
        summary=summary,
        owner_sub=owner_sub,
        artifact_keys=artifact_keys,
        owner_sort=owner_sort,
        snapshot_key=snapshot_key,
        snapshot_version=snapshot_version,
    )


def _encode_cursor(pid: str) -> str:
    return base64.urlsafe_b64encode(pid.encode("utf-8")).decode("ascii").rstrip("=")


def _decode_cursor(cursor: str) -> str:
    try:
        padded = cursor + "=" * (-len(cursor) % 4)
        pid = base64.b64decode(padded, altchars=b"-_", validate=True).decode("utf-8")
    except (ValueError, UnicodeError) as exc:
        raise InvalidCursor("invalid session cursor") from exc
    if not pid or len(pid) > 128:
        raise InvalidCursor("invalid session cursor")
    return pid


class DynamoSessionCatalog:
    def __init__(self, table, *, owner_index: str = "OwnerSessionsIndex"):
        self.table = table
        self.owner_index = owner_index

    def _row(self, pid: str) -> dict | None:
        response = self.table.get_item(Key={"pid": pid}, ConsistentRead=True)
        row = response.get("Item")
        return row if isinstance(row, dict) else None

    def get_owned(self, pid: str, owner_sub: str) -> PublishedSession | None:
        row = self._row(pid)
        if not row or str(row.get("owner_sub") or "") != owner_sub:
            return None
        return _summary_from_row(row)

    def create_for_owner(self, owner_sub: str, *, title: str) -> PublishedSession:
        timestamp = int(time.time())
        pid = uuid.uuid4().hex
        row = {
            "pid": pid,
            "owner_sub": owner_sub,
            "owner_sort": f"CREATED#{timestamp:020d}#{pid}",
            "ts": timestamp,
            "updated_at": timestamp,
            "title": title,
            "status": "draft",
            "artifact_keys": "[]",
        }
        self.table.put_item(
            Item=row,
            ConditionExpression="attribute_not_exists(pid)",
        )
        parsed = _summary_from_row(row)
        if parsed is None:  # pragma: no cover - constructed row is valid by design
            raise RuntimeError("failed to construct session draft")
        return parsed

    def rename_owned(
        self, pid: str, owner_sub: str, *, title: str
    ) -> PublishedSession | None:
        from botocore.exceptions import ClientError

        timestamp = int(time.time())
        try:
            response = self.table.update_item(
                Key={"pid": pid},
                UpdateExpression="SET title = :title, updated_at = :updated",
                ConditionExpression="owner_sub = :owner",
                ExpressionAttributeValues={
                    ":title": title,
                    ":updated": timestamp,
                    ":owner": owner_sub,
                },
                ReturnValues="ALL_NEW",
            )
        except ClientError as exc:
            if exc.response.get("Error", {}).get("Code") == "ConditionalCheckFailedException":
                return None
            raise
        return _summary_from_row(response.get("Attributes") or {})

    def _batch_rows(self, pids: list[str]) -> dict[str, dict]:
        if not pids:
            return {}
        pending = [{"pid": pid} for pid in pids]
        rows: dict[str, dict] = {}
        for _ in range(4):
            response = self.table.meta.client.batch_get_item(
                RequestItems={self.table.name: {"Keys": pending}}
            )
            for row in response.get("Responses", {}).get(self.table.name, []):
                if row.get("pid"):
                    rows[str(row["pid"])] = row
            pending = response.get("UnprocessedKeys", {}).get(
                self.table.name, {}
            ).get("Keys", [])
            if not pending:
                return rows
        raise RuntimeError("session metadata batch read did not complete")

    def list_for_owner(
        self, owner_sub: str, *, limit: int, cursor: str | None
    ) -> SessionPage:
        from boto3.dynamodb.conditions import Key

        query: dict = {
            "IndexName": self.owner_index,
            "KeyConditionExpression": Key("owner_sub").eq(owner_sub),
            "ScanIndexForward": False,
            "Limit": limit,
        }
        if cursor:
            prior_pid = _decode_cursor(cursor)
            prior = self.get_owned(prior_pid, owner_sub)
            if prior is None:
                raise InvalidCursor("invalid session cursor")
            query["ExclusiveStartKey"] = {
                "pid": prior.summary.pid,
                "owner_sub": prior.owner_sub,
                "owner_sort": prior.owner_sort,
            }
        response = self.table.query(**query)
        ordered_pids = [
            str(row.get("pid")) for row in response.get("Items", []) if row.get("pid")
        ]
        rows = self._batch_rows(ordered_pids)
        items = []
        for pid in ordered_pids:
            parsed = _summary_from_row(rows.get(pid, {}))
            if parsed is not None and parsed.owner_sub == owner_sub:
                items.append(parsed)
        last = response.get("LastEvaluatedKey")
        next_cursor = None
        if isinstance(last, dict) and last.get("pid"):
            next_cursor = _encode_cursor(str(last["pid"]))
        return SessionPage(items=items, next_cursor=next_cursor)


class S3ArtifactStore:
    def __init__(self, client, *, bucket: str):
        self.client = client
        self.bucket = bucket

    def get(self, key: str, *, filename: str) -> StoredArtifact | None:
        try:
            response = self.client.get_object(Bucket=self.bucket, Key=key)
        except Exception as exc:
            from botocore.exceptions import ClientError

            if isinstance(exc, ClientError) and exc.response.get("Error", {}).get(
                "Code"
            ) in {"NoSuchKey", "404", "NotFound"}:
                return None
            raise
        return StoredArtifact(
            body=response["Body"],
            content_type=response.get("ContentType"),
            content_length=response.get("ContentLength"),
            filename=filename,
        )

    def get_workspace(self, key: str) -> WorkspaceSnapshot | None:
        try:
            response = self.client.get_object(Bucket=self.bucket, Key=key)
            payload = json.loads(response["Body"].read())
            return WorkspaceSnapshot.model_validate(payload)
        except Exception as exc:
            from botocore.exceptions import ClientError

            if isinstance(exc, ClientError) and exc.response.get("Error", {}).get(
                "Code"
            ) in {"NoSuchKey", "404", "NotFound"}:
                return None
            if isinstance(exc, (json.JSONDecodeError, UnicodeDecodeError, ValidationError)):
                return None
            raise
