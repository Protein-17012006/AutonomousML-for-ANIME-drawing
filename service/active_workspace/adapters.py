"""Boto3 adapter for the active workspace.

It shares the `copilot_sessions` table with published session history, which is
the one thing to be careful about: a workspace is an IN-PROGRESS run, and the
artist's history must not list it as a saved session. Both row kinds therefore
carry **no `owner_sort`**, which keeps them out of the sparse `OwnerSessionsIndex`
that `list_for_owner` queries. Two row kinds, both keyed off `pid`:

    WS#<workspace_id>     the workspace record, event log included
    WSACTIVE#<owner_sub>  a pointer to that owner's one open workspace

The pointer exists so "which run is open?" is a `get_item`, not a query — no
second index, and nothing to keep consistent with the sessions GSI.
"""
from __future__ import annotations

import json
import threading

from pydantic import ValidationError

from service.active_workspace.models import (
    ActiveWorkspace,
    WorkspaceAsset,
    WorkspaceEvent,
)
from service.session_history.models import WorkspaceSnapshot, WorkspaceUpload


WORKSPACE_PREFIX = "WS#"
ACTIVE_PREFIX = "WSACTIVE#"

# DynamoDB caps an item at 400 KB. Stay well under it: the log is only one of
# several attributes, and being wrong here fails the write, not the read.
_MAX_EVENTS_BYTES = 300_000


def _json(value) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def _loads(value, default):
    if not isinstance(value, str):
        return default
    try:
        return json.loads(value)
    except (TypeError, ValueError):
        return default


def _trim(events: list[WorkspaceEvent]) -> list[WorkspaceEvent]:
    """Drop the OLDEST `pair` events until the log fits.

    Safe because the snapshot carries the complete pair list and the client
    rehydrates from it whenever `revision` differs from its cached copy — so a
    trimmed replay degrades to a snapshot reload, never to a silent gap. The
    terminal `publish`/`error` frames are never dropped: the client closes its
    stream on those, and losing one leaves a browser reconnecting forever.
    """
    encoded = [(event, len(_json(event.data).encode())) for event in events]
    total = sum(size for _event, size in encoded)
    if total <= _MAX_EVENTS_BYTES:
        return events
    last = len(encoded) - 1
    kept: list[WorkspaceEvent] = []
    for index, (event, size) in enumerate(encoded):
        droppable = event.name == "pair" and index != last
        if total > _MAX_EVENTS_BYTES and droppable:
            total -= size
            continue
        kept.append(event)
    return kept


class DynamoActiveWorkspaceStore:
    def __init__(self, table):
        self.table = table
        self._lock = threading.RLock()

    # --- row mapping -------------------------------------------------------

    @staticmethod
    def _to_row(workspace: ActiveWorkspace) -> dict:
        events = _trim(list(workspace.events))
        return {
            "pid": WORKSPACE_PREFIX + workspace.workspace_id,
            "owner_sub": workspace.owner_sub,
            # NO owner_sort: keeps this row out of the sessions owner index.
            "kind": "active_workspace",
            "state": workspace.state,
            "revision": int(workspace.revision),
            "published_pid": workspace.published_pid or "",
            "snapshot": (workspace.snapshot.model_dump_json()
                         if workspace.snapshot else ""),
            "upload": (workspace.upload.model_dump_json()
                       if workspace.upload else ""),
            "assets": _json([asset.model_dump() for asset in workspace.assets]),
            "artifact_urls": _json(dict(workspace.artifact_urls)),
            "events": _json([{"sequence": event.sequence, "name": event.name,
                              "data": event.data} for event in events]),
        }

    @staticmethod
    def _from_row(row: dict) -> ActiveWorkspace | None:
        pid = str(row.get("pid") or "")
        owner_sub = str(row.get("owner_sub") or "")
        if not pid.startswith(WORKSPACE_PREFIX) or not owner_sub:
            return None
        snapshot = None
        raw_snapshot = row.get("snapshot")
        if isinstance(raw_snapshot, str) and raw_snapshot:
            try:
                snapshot = WorkspaceSnapshot.model_validate_json(raw_snapshot)
            except ValidationError:
                snapshot = None
        upload = None
        raw_upload = row.get("upload")
        if isinstance(raw_upload, str) and raw_upload:
            try:
                upload = WorkspaceUpload.model_validate_json(raw_upload)
            except ValidationError:
                upload = None
        assets = []
        for item in _loads(row.get("assets"), []):
            try:
                assets.append(WorkspaceAsset.model_validate(item))
            except ValidationError:
                continue
        events = [
            WorkspaceEvent(sequence=int(item["sequence"]), name=str(item["name"]),
                           data=dict(item.get("data") or {}))
            for item in _loads(row.get("events"), [])
            if isinstance(item, dict) and "sequence" in item and "name" in item
        ]
        artifact_urls = _loads(row.get("artifact_urls"), {})
        return ActiveWorkspace(
            workspace_id=pid[len(WORKSPACE_PREFIX):],
            owner_sub=owner_sub,
            state=str(row.get("state") or "draft"),
            revision=int(row.get("revision") or 0),
            published_pid=str(row.get("published_pid") or "") or None,
            snapshot=snapshot,
            upload=upload,
            assets=assets,
            artifact_urls=artifact_urls if isinstance(artifact_urls, dict) else {},
            events=events,
        )

    # --- port --------------------------------------------------------------

    def _row(self, pid: str) -> dict | None:
        response = self.table.get_item(Key={"pid": pid}, ConsistentRead=True)
        row = response.get("Item")
        return row if isinstance(row, dict) else None

    def active_for(self, owner_sub: str) -> ActiveWorkspace | None:
        if not owner_sub:
            return None
        pointer = self._row(ACTIVE_PREFIX + owner_sub)
        workspace_id = str((pointer or {}).get("workspace_id") or "")
        if not workspace_id:
            return None
        return self.get_owned(workspace_id, owner_sub)

    def get_owned(self, workspace_id: str, owner_sub: str) -> ActiveWorkspace | None:
        row = self._row(WORKSPACE_PREFIX + workspace_id)
        if row is None or str(row.get("owner_sub") or "") != owner_sub:
            return None
        return self._from_row(row)

    def save(self, workspace: ActiveWorkspace) -> None:
        with self._lock:
            self.table.put_item(Item=self._to_row(workspace))

    def delete(self, workspace_id: str, owner_sub: str) -> None:
        with self._lock:
            if self.get_owned(workspace_id, owner_sub) is None:
                return
            self.table.delete_item(Key={"pid": WORKSPACE_PREFIX + workspace_id})
            pointer = self._row(ACTIVE_PREFIX + owner_sub) or {}
            if str(pointer.get("workspace_id") or "") == workspace_id:
                self.table.delete_item(Key={"pid": ACTIVE_PREFIX + owner_sub})

    def set_active(self, owner_sub: str, workspace_id: str | None) -> None:
        with self._lock:
            if workspace_id is None:
                self.table.delete_item(Key={"pid": ACTIVE_PREFIX + owner_sub})
                return
            self.table.put_item(Item={
                "pid": ACTIVE_PREFIX + owner_sub,
                "owner_sub": owner_sub,       # again, no owner_sort
                "kind": "active_workspace_pointer",
                "workspace_id": workspace_id,
            })
