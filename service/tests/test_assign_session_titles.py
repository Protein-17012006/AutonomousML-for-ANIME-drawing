from __future__ import annotations

import boto3
from moto import mock_aws

from scripts.assign_session_titles import (
    apply_manifest,
    build_manifest,
    rollback_manifest,
)


def test_title_manifest_is_deterministic_and_preserves_existing_values():
    rows = [
        {"pid": "a", "owner_sub": "owner", "ts": 1},
        {"pid": "b", "owner_sub": "owner", "ts": 2, "title": "Kept"},
        {"pid": "c", "ts": 3},
    ]
    first = build_manifest(rows, seed=7, table_name="sessions")
    second = build_manifest(rows, seed=7, table_name="sessions")
    assert [op["assigned_title"] for op in first["operations"]] == [
        op["assigned_title"] for op in second["operations"]
    ]
    assert {op["pid"] for op in first["operations"]} == {"a", "b"}
    kept = next(op for op in first["operations"] if op["pid"] == "b")
    assert kept["assigned_title"] == "Kept" and kept["add_title"] is False


@mock_aws
def test_title_manifest_applies_and_rolls_back_only_added_fields():
    table = boto3.resource("dynamodb", region_name="us-east-1").create_table(
        TableName="sessions",
        BillingMode="PAY_PER_REQUEST",
        AttributeDefinitions=[{"AttributeName": "pid", "AttributeType": "S"}],
        KeySchema=[{"AttributeName": "pid", "KeyType": "HASH"}],
    )
    table.put_item(Item={"pid": "a", "owner_sub": "owner", "ts": 1, "keep": "yes"})
    table.put_item(Item={"pid": "b", "owner_sub": "owner", "ts": 2, "title": "Kept"})
    manifest = build_manifest(
        [table.get_item(Key={"pid": "a"})["Item"], table.get_item(Key={"pid": "b"})["Item"]],
        seed=7,
        table_name="sessions",
    )
    apply_manifest(table, manifest)
    assert table.get_item(Key={"pid": "a"})["Item"]["status"] == "complete"
    assert table.get_item(Key={"pid": "b"})["Item"]["title"] == "Kept"
    rollback_manifest(table, manifest)
    assert table.get_item(Key={"pid": "a"})["Item"] == {
        "pid": "a", "owner_sub": "owner", "ts": 1, "keep": "yes"
    }
    assert table.get_item(Key={"pid": "b"})["Item"]["title"] == "Kept"
    assert "status" not in table.get_item(Key={"pid": "b"})["Item"]
