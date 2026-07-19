"""Dry-run ownership assignment and rollback boundaries."""
import boto3
from moto import mock_aws

from scripts.assign_session_owners import (
    apply_manifest,
    build_manifest,
    owner_sort_key,
    resolve_users,
    rollback_manifest,
)


class FakeCognito:
    def __init__(self, users):
        self.users = users

    def admin_get_user(self, *, UserPoolId, Username):
        return self.users[Username]


def _user(username, sub, enabled=True):
    return {
        "Username": username,
        "Enabled": enabled,
        "UserAttributes": [{"Name": "sub", "Value": sub}],
    }


def test_resolves_exact_enabled_distinct_cognito_users():
    names = ["mail@example.com", "hoang", "Google_123"]
    client = FakeCognito({
        name: _user(name, f"sub-{index}") for index, name in enumerate(names)
    })
    users = resolve_users(client, user_pool_id="pool", usernames=names)
    assert [user["username"] for user in users] == names
    assert [user["sub"] for user in users] == ["sub-0", "sub-1", "sub-2"]


def test_manifest_assigns_all_ownerless_deterministically_and_preserves_owner():
    users = [
        {"username": "a", "sub": "sub-a"},
        {"username": "b", "sub": "sub-b"},
        {"username": "c", "sub": "sub-c"},
    ]
    rows = [
        {"pid": "p1", "ts": 1},
        {"pid": "p2", "ts": 2},
        {"pid": "p3", "ts": 3},
        {"pid": "owned", "ts": 4, "owner_sub": "existing"},
        {
            "pid": "indexed",
            "ts": 5,
            "owner_sub": "existing",
            "owner_sort": owner_sort_key(5, "indexed"),
        },
    ]
    first = build_manifest(
        rows, users, seed=20260719, table_name="table", user_pool_id="pool"
    )
    second = build_manifest(
        rows, users, seed=20260719, table_name="table", user_pool_id="pool"
    )
    assert [op["pid"] for op in first["operations"]] == [
        op["pid"] for op in second["operations"]
    ]
    assignments = [
        operation for operation in first["operations"]
        if operation["kind"] == "assign_owner"
    ]
    assert {operation["pid"] for operation in assignments} == {"p1", "p2", "p3"}
    assert {operation["assigned_owner_sub"] for operation in assignments} == {
        "sub-a", "sub-b", "sub-c"
    }
    owned = next(op for op in first["operations"] if op["pid"] == "owned")
    assert owned["kind"] == "add_owner_sort"
    assert owned["assigned_owner_sub"] == "existing"
    assert all(op["pid"] != "indexed" for op in first["operations"])


@mock_aws
def test_apply_and_rollback_touch_only_manifest_attributes():
    table = boto3.resource("dynamodb", region_name="us-east-1").create_table(
        TableName="sessions",
        BillingMode="PAY_PER_REQUEST",
        AttributeDefinitions=[{"AttributeName": "pid", "AttributeType": "S"}],
        KeySchema=[{"AttributeName": "pid", "KeyType": "HASH"}],
    )
    table.put_item(Item={"pid": "ownerless", "ts": 1, "keep": "yes"})
    table.put_item(Item={"pid": "owned", "ts": 2, "owner_sub": "existing"})
    users = [{"username": "a", "sub": "sub-a"}, {"username": "b", "sub": "sub-b"}]
    manifest = build_manifest(
        [
            {"pid": "ownerless", "ts": 1},
            {"pid": "owned", "ts": 2, "owner_sub": "existing"},
        ],
        users,
        seed=20260719,
        table_name="sessions",
        user_pool_id="pool",
    )
    apply_manifest(table, manifest)
    assert table.get_item(Key={"pid": "ownerless"})["Item"]["owner_sub"] == "sub-a"
    assert table.get_item(Key={"pid": "owned"})["Item"]["owner_sort"]

    rollback_manifest(table, manifest)
    ownerless = table.get_item(Key={"pid": "ownerless"})["Item"]
    owned = table.get_item(Key={"pid": "owned"})["Item"]
    assert ownerless == {"pid": "ownerless", "ts": 1, "keep": "yes"}
    assert owned == {"pid": "owned", "ts": 2, "owner_sub": "existing"}
