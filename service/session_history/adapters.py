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
    QaTranscriptSnapshot,
    QaTranscriptTurn,
    WorkspaceSnapshot,
)


# One turn's stored multi-agent exchange. The snapshot is rewritten whole on
# every append, so this bounds the growth; reads are never capped.
_MAX_STORED_TRANSCRIPT_ENTRIES = 40

_LINK_NAMES = {
    "montage.png": "montage",
    "report.md": "report",
    "reconstructed.mp4": "video",
    "compare.mp4": "compare",
}
_ALLOWED_SUFFIXES = {".png", ".md", ".mp4"}


class InvalidCursor(ValueError):
    pass


class SessionDeleteConflict(RuntimeError):
    """The owned record exists but is not a completed history session."""


class ArtifactDeletionError(RuntimeError):
    """A durable session prefix could not be fully removed from S3."""


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
    prefix = f"artifacts/{pid}/"
    if not isinstance(value, str) or not value.startswith(prefix):
        return None
    relative = value[len(prefix):]
    # Existing sessions used the canonical path. New mutable review revisions
    # are immutable object generations below revisions/<opaque-id>/.
    if relative == "workspace.v1.json":
        return value
    parts = pathlib.PurePosixPath(relative).parts
    if len(parts) == 3 and parts[0] == "revisions" and parts[2] == "workspace.v1.json" and parts[1]:
        return value
    return None


def _safe_message_snapshot_key(pid: str, value) -> str | None:
    if not isinstance(value, str):
        return None
    prefix = f"artifacts/{pid}/messages.v1/"
    if not value.startswith(prefix) or not value.endswith(".json"):
        return None
    relative = value[len(prefix):]
    return value if relative and "/" not in relative and "\\" not in relative else None


def _safe_artifact_keys(pid: str, value) -> dict[str, str]:
    prefix = f"artifacts/{pid}/"
    safe: dict[str, str] = {}
    for candidate in _json_list(value):
        if not isinstance(candidate, str) or not candidate.startswith(prefix):
            continue
        relative = candidate[len(prefix):]
        if not relative or "\\" in relative:
            continue
        path = pathlib.PurePosixPath(relative)
        # Accept legacy flat artifacts and current immutable revision objects.
        if len(path.parts) == 1:
            name = path.name
        elif len(path.parts) == 3 and path.parts[0] == "revisions" and path.parts[1]:
            name = path.name
        else:
            continue
        if path.suffix.lower() not in _ALLOWED_SUFFIXES:
            continue
        safe[name] = candidate
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
    message_version = _integer(row.get("message_version")) or None
    message_snapshot_key = _safe_message_snapshot_key(
        pid, row.get("message_snapshot_key")
    )
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
        message_snapshot_key=message_snapshot_key,
        message_version=message_version,
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

    def begin_delete_complete_owned(
        self, pid: str, owner_sub: str
    ) -> PublishedSession | None:
        """Hide a completed session while its S3 prefix is being removed.

        The temporary status also prevents an in-flight Q&A or review revision
        from moving Dynamo's pointers while deletion is under way.
        """
        from botocore.exceptions import ClientError

        try:
            response = self.table.update_item(
                Key={"pid": pid},
                UpdateExpression="SET #status = :deleting",
                ConditionExpression="owner_sub = :owner AND #status = :complete",
                ExpressionAttributeNames={"#status": "status"},
                ExpressionAttributeValues={
                    ":owner": owner_sub,
                    ":complete": "complete",
                    ":deleting": "deleting",
                },
                ReturnValues="ALL_OLD",
            )
        except ClientError as exc:
            if exc.response.get("Error", {}).get("Code") != "ConditionalCheckFailedException":
                raise
            row = self._row(pid)
            if not row or str(row.get("owner_sub") or "") != owner_sub:
                return None
            raise SessionDeleteConflict("only completed sessions can be deleted") from exc
        return _summary_from_row(response.get("Attributes") or {})

    def restore_delete_complete_owned(self, pid: str, owner_sub: str) -> None:
        self.table.update_item(
            Key={"pid": pid},
            UpdateExpression="SET #status = :complete",
            ConditionExpression="owner_sub = :owner AND #status = :deleting",
            ExpressionAttributeNames={"#status": "status"},
            ExpressionAttributeValues={
                ":owner": owner_sub,
                ":deleting": "deleting",
                ":complete": "complete",
            },
        )

    def finish_delete_complete_owned(self, pid: str, owner_sub: str) -> None:
        self.table.delete_item(
            Key={"pid": pid},
            ConditionExpression="owner_sub = :owner AND #status = :deleting",
            ExpressionAttributeNames={"#status": "status"},
            ExpressionAttributeValues={":owner": owner_sub, ":deleting": "deleting"},
        )

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

    def get_transcript(self, key: str) -> QaTranscriptSnapshot | None:
        try:
            response = self.client.get_object(Bucket=self.bucket, Key=key)
            payload = json.loads(response["Body"].read())
            return QaTranscriptSnapshot.model_validate(payload)
        except Exception as exc:
            from botocore.exceptions import ClientError

            if isinstance(exc, ClientError) and exc.response.get("Error", {}).get(
                "Code"
            ) in {"NoSuchKey", "404", "NotFound"}:
                return None
            if isinstance(exc, (json.JSONDecodeError, UnicodeDecodeError, ValidationError)):
                return None
            raise

    def delete_prefix(self, prefix: str) -> None:
        """Delete every current object under one server-controlled session prefix."""
        try:
            paginator = self.client.get_paginator("list_objects_v2")
            for page in paginator.paginate(Bucket=self.bucket, Prefix=prefix):
                objects = [
                    {"Key": item["Key"]}
                    for item in page.get("Contents", [])
                    if isinstance(item.get("Key"), str)
                ]
                for offset in range(0, len(objects), 1000):
                    response = self.client.delete_objects(
                        Bucket=self.bucket,
                        Delete={"Objects": objects[offset:offset + 1000], "Quiet": True},
                    )
                    if response.get("Errors"):
                        raise ArtifactDeletionError("could not delete all session artifacts")
        except ArtifactDeletionError:
            raise
        except Exception as exc:
            raise ArtifactDeletionError("could not delete session artifacts") from exc


class TranscriptStoreError(RuntimeError):
    pass


class DynamoTranscriptStore:
    """Versioned transcript pointer in the owned session row, payload in S3."""

    def __init__(self, table, artifacts: S3ArtifactStore):
        self.table = table
        self.artifacts = artifacts

    def append_turn(self, pid: str, owner_sub: str, *, question: str,
                    answer: str, grounded: bool,
                    kind: str = "ask", transcript=None, action=None,
                    rejected_tool: str | None = None) -> QaTranscriptTurn:
        from botocore.exceptions import ClientError

        # Cap on WRITE, never on read: the whole snapshot is rewritten on every
        # append, so an unbounded multi-agent transcript would grow the object
        # each turn. An already-stored turn must still load whatever its size.
        entries = [
            {str(k): (v if isinstance(v, (bool, int, float)) else str(v)[:600])
             for k, v in entry.items()}
            for entry in (transcript or [])[:_MAX_STORED_TRANSCRIPT_ENTRIES]
            if isinstance(entry, dict)
        ]

        for _ in range(4):
            row = self.table.get_item(Key={"pid": pid}, ConsistentRead=True).get("Item")
            if not isinstance(row, dict) or str(row.get("owner_sub") or "") != owner_sub:
                raise TranscriptStoreError("durable session not found")
            if str(row.get("status") or "") != "complete":
                raise TranscriptStoreError("durable session is not ready")
            previous_version = _integer(row.get("message_version"))
            previous_key = _safe_message_snapshot_key(pid, row.get("message_snapshot_key"))
            transcript = self.artifacts.get_transcript(previous_key) if previous_key else None
            if previous_key and transcript is None:
                raise TranscriptStoreError("stored Q&A transcript is unavailable")
            turns = list(transcript.turns) if transcript else []
            timestamp = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
            turn = QaTranscriptTurn(
                turn_id=uuid.uuid4().hex,
                question=question,
                answer=answer,
                grounded=grounded,
                answered_at=timestamp,
                kind=kind if kind in ("ask", "agent") else "ask",
                transcript=entries,
                action=action if isinstance(action, dict) else None,
                rejected_tool=rejected_tool or None,
            )
            turns.append(turn)
            next_version = previous_version + 1
            key = f"artifacts/{pid}/messages.v1/{next_version}-{uuid.uuid4().hex}.json"
            snapshot = QaTranscriptSnapshot(
                schema_version=1, pid=pid, turns=turns
            )
            self.artifacts.client.put_object(
                Bucket=self.artifacts.bucket,
                Key=key,
                Body=snapshot.model_dump_json().encode("utf-8"),
                ContentType="application/json",
            )
            try:
                self.table.update_item(
                    Key={"pid": pid},
                    UpdateExpression=(
                        "SET message_snapshot_key = :key, message_version = :next, "
                        "message_count = :count, messages_updated_at = :updated"
                    ),
                    ConditionExpression=(
                        "owner_sub = :owner AND #status = :complete AND "
                        "(attribute_not_exists(message_version) OR message_version = :previous)"
                    ),
                    ExpressionAttributeNames={"#status": "status"},
                    ExpressionAttributeValues={
                        ":key": key,
                        ":next": next_version,
                        ":count": len(turns),
                        ":updated": int(time.time()),
                        ":owner": owner_sub,
                        ":complete": "complete",
                        ":previous": previous_version,
                    },
                )
                return turn
            except ClientError as exc:
                if exc.response.get("Error", {}).get("Code") != "ConditionalCheckFailedException":
                    raise
        raise TranscriptStoreError("Q&A transcript changed; retry")
