"""Boto3 adapters for the durable session table and artifact bucket."""
from __future__ import annotations

import base64
from datetime import datetime, timezone
from decimal import Decimal
import json
import pathlib

from service.session_history.models import (
    ArtifactLinks,
    PublishedSession,
    SessionPage,
    SessionSummary,
    SessionSummaryCounts,
    StoredArtifact,
)


_LINK_NAMES = {
    "montage.png": "montage",
    "report.md": "report",
    "reconstructed.mp4": "video",
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
        created_at=_created_at(timestamp),
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
        items = [
            parsed
            for row in response.get("Items", [])
            if (parsed := _summary_from_row(row)) is not None
        ]
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
