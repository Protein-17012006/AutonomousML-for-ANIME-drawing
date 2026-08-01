"""Durable storage for the active workspace.

Without this the store is in-memory: a workspace dies with the process, so
"resume after a reload" holds only until the service restarts. These tests are
what make the feature survive a deploy.

The sharpest risk here is not losing data — it is LEAKING it. Workspaces share
the `copilot_sessions` table with published session history, so a row written
carelessly would surface in the artist's session list as a finished session.
"""
from __future__ import annotations

import boto3
from moto import mock_aws
import pytest

from service.active_workspace.adapters import DynamoActiveWorkspaceStore
from service.active_workspace.service import ActiveWorkspaceService
from service.session_history.adapters import DynamoSessionCatalog
from service.session_history.models import WorkspaceSnapshot, WorkspaceUpload
from service.sessions.schemas import PairEvent, ResultEvent


def _snapshot(n_pairs: int = 2) -> WorkspaceSnapshot:
    return WorkspaceSnapshot(
        schema_version=1,
        upload=WorkspaceUpload(mode="frames", label="3 keyframes",
                               filenames=["0.png", "1.png"]),
        pairs=[PairEvent(index=i, action="fill", qa="pass", keys_requested=0)
               for i in range(n_pairs)],
        result=ResultEvent(n_autopass=n_pairs, n_corrected=0,
                           keys_requested_total=0, flagged=[], abstained=[],
                           needs_key=[], artifacts={}),
    )


@pytest.fixture
def table():
    with mock_aws():
        dynamodb = boto3.resource("dynamodb", region_name="ap-southeast-1")
        yield dynamodb.create_table(
            TableName="copilot_sessions",
            BillingMode="PAY_PER_REQUEST",
            AttributeDefinitions=[
                {"AttributeName": "pid", "AttributeType": "S"},
                {"AttributeName": "owner_sub", "AttributeType": "S"},
                {"AttributeName": "owner_sort", "AttributeType": "S"},
            ],
            KeySchema=[{"AttributeName": "pid", "KeyType": "HASH"}],
            GlobalSecondaryIndexes=[{
                "IndexName": "OwnerSessionsIndex",
                "KeySchema": [
                    {"AttributeName": "owner_sub", "KeyType": "HASH"},
                    {"AttributeName": "owner_sort", "KeyType": "RANGE"},
                ],
                "Projection": {"ProjectionType": "ALL"},
            }],
        )


def _service(table):
    return ActiveWorkspaceService(DynamoActiveWorkspaceStore(table))


def test_a_workspace_round_trips_through_dynamodb(table):
    svc = _service(table)
    opened = svc.open_workspace("owner-1", upload=_snapshot().upload)
    svc.append_event(opened.workspace_id, "owner-1", "pair",
                     {"index": 0, "action": "fill"})
    svc.record_snapshot(opened.workspace_id, "owner-1", _snapshot())

    found = svc.active_for("owner-1")
    assert found.workspace_id == opened.workspace_id
    assert found.state == "complete"
    assert found.revision == 1
    assert found.snapshot.pairs[1].index == 1
    assert [e.sequence for e in found.events] == [1]


def test_a_workspace_survives_a_new_store_instance(table):
    """The point of the whole adapter: a restart must not lose the run."""
    opened = _service(table).open_workspace("owner-1", upload=_snapshot().upload)
    _service(table).record_snapshot(opened.workspace_id, "owner-1", _snapshot())

    revived = _service(table).active_for("owner-1")
    assert revived is not None and revived.workspace_id == opened.workspace_id
    assert revived.snapshot is not None


def test_a_workspace_row_never_appears_in_session_history(table):
    """Workspaces share the table with published sessions. Their rows carry no
    `owner_sort`, which keeps them out of the sparse owner index — otherwise an
    in-progress run would show up in the artist's history as a saved session."""
    svc = _service(table)
    svc.open_workspace("owner-1", upload=_snapshot().upload)
    svc.record_snapshot(svc.active_for("owner-1").workspace_id, "owner-1",
                        _snapshot())

    page = DynamoSessionCatalog(table).list_for_owner("owner-1", limit=20,
                                                      cursor=None)
    assert page.items == []


def test_another_owner_cannot_read_or_delete_it(table):
    svc = _service(table)
    workspace = svc.open_workspace("owner-1", upload=_snapshot().upload)
    assert svc.get(workspace.workspace_id, "owner-2") is None
    assert svc.discard(workspace.workspace_id, "owner-2") is False
    assert svc.active_for("owner-1") is not None


def test_discard_clears_both_the_record_and_the_active_pointer(table):
    svc = _service(table)
    workspace = svc.open_workspace("owner-1", upload=_snapshot().upload)
    assert svc.discard(workspace.workspace_id, "owner-1") is True
    assert _service(table).active_response("owner-1") == {"workspace": None}


def test_the_event_log_is_trimmed_before_it_can_exceed_the_item_limit(table):
    """DynamoDB caps an item at 400 KB. Dropping the OLDEST pair events is safe
    precisely because the snapshot carries the full pair list and the client
    rehydrates from it whenever `revision` differs from its cache — so a trimmed
    replay degrades to a snapshot reload, never to a silent gap."""
    svc = _service(table)
    workspace = svc.open_workspace("owner-1", upload=_snapshot().upload)
    fat = {"index": 0, "action": "fill", "reason": "x" * 8_000}
    for _ in range(80):
        svc.append_event(workspace.workspace_id, "owner-1", "pair", dict(fat))

    stored = svc.get(workspace.workspace_id, "owner-1")
    assert len(stored.events) < 80                      # trimmed
    # Sequences remain strictly increasing and the newest is never dropped.
    sequences = [event.sequence for event in stored.events]
    assert sequences == sorted(sequences)
    assert sequences[-1] == 80


def test_a_terminal_publish_event_is_never_trimmed_away(table):
    """The client closes its stream on `publish`. Losing it to a size trim would
    leave a browser reconnecting forever against a finished run."""
    svc = _service(table)
    workspace = svc.open_workspace("owner-1", upload=_snapshot().upload)
    svc.append_event(workspace.workspace_id, "owner-1", "publish",
                     {"published": True, "pid": "pid-1"})
    fat = {"index": 0, "action": "fill", "reason": "x" * 8_000}
    for _ in range(80):
        svc.append_event(workspace.workspace_id, "owner-1", "pair", dict(fat))

    names = [event.name for event in
             svc.get(workspace.workspace_id, "owner-1").events]
    assert "publish" in names
