"""Assign durable ownerless sessions to explicit Cognito test users.

Dry-run is the default. Applying or rolling back requires both ``--apply`` and
an exact confirmation phrase. The manifest is the audit and rollback boundary.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import os
import pathlib
import random
import sys


DEFAULT_USERS = (
    "luudatphong25@gmail.com",
    "hoang",
    "Google_115024632640774298668",
)
DEFAULT_SEED = 20260719
APPLY_CONFIRMATION = "ASSIGN_ALL_OWNERLESS"
ROLLBACK_CONFIRMATION = "ROLLBACK_OWNER_ASSIGNMENTS"


def owner_sort_key(timestamp: int, pid: str) -> str:
    return f"CREATED#{timestamp:020d}#{pid}"


def _arguments(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--table", default=os.getenv("AWS_SESSIONS_TABLE"))
    parser.add_argument(
        "--user-pool-id", default=os.getenv("COPILOT_COGNITO_USER_POOL_ID")
    )
    parser.add_argument("--region", default=os.getenv("AWS_REGION", "ap-southeast-1"))
    parser.add_argument("--users", nargs="+", default=list(DEFAULT_USERS))
    parser.add_argument("--seed", type=int, default=DEFAULT_SEED)
    parser.add_argument("--manifest", type=pathlib.Path)
    parser.add_argument("--rollback-manifest", type=pathlib.Path)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--confirm", default="")
    args = parser.parse_args(argv)
    if not args.table:
        parser.error("--table or AWS_SESSIONS_TABLE is required")
    if not args.user_pool_id:
        parser.error("--user-pool-id or COPILOT_COGNITO_USER_POOL_ID is required")
    if args.rollback_manifest and args.manifest:
        parser.error("--manifest and --rollback-manifest are mutually exclusive")
    return args


def _attribute(attributes: list[dict], name: str) -> str | None:
    for attribute in attributes:
        if attribute.get("Name") == name:
            value = str(attribute.get("Value") or "").strip()
            return value or None
    return None


def resolve_users(cognito, *, user_pool_id: str, usernames: list[str]) -> list[dict]:
    resolved = []
    seen_subs: set[str] = set()
    for username in usernames:
        response = cognito.admin_get_user(
            UserPoolId=user_pool_id, Username=username
        )
        if not response.get("Enabled", False):
            raise RuntimeError(f"Cognito user is disabled: {username}")
        sub = _attribute(response.get("UserAttributes", []), "sub")
        if not sub:
            raise RuntimeError(f"Cognito user has no sub: {username}")
        if sub in seen_subs:
            raise RuntimeError(f"Cognito users resolve to a duplicate sub: {username}")
        seen_subs.add(sub)
        resolved.append({"username": username, "sub": sub})
    if len(resolved) < 2:
        raise RuntimeError("at least two distinct enabled Cognito users are required")
    return resolved


def scan_sessions(table) -> list[dict]:
    rows: list[dict] = []
    request: dict = {}
    while True:
        response = table.scan(**request)
        rows.extend(response.get("Items", []))
        last = response.get("LastEvaluatedKey")
        if not last:
            return rows
        request["ExclusiveStartKey"] = last


def build_manifest(rows: list[dict], users: list[dict], *, seed: int,
                   table_name: str, user_pool_id: str) -> dict:
    ownerless = [row for row in rows if not str(row.get("owner_sub") or "").strip()]
    ownerless.sort(key=lambda row: str(row.get("pid") or ""))
    random.Random(seed).shuffle(ownerless)
    operations: list[dict] = []
    for index, row in enumerate(ownerless):
        pid = str(row.get("pid") or "").strip()
        timestamp = int(row.get("ts") or 0)
        if not pid or timestamp <= 0:
            raise RuntimeError(f"session cannot be assigned safely: {row!r}")
        user = users[index % len(users)]
        operations.append({
            "kind": "assign_owner",
            "pid": pid,
            "prior_owner_sub": None,
            "prior_owner_sort": row.get("owner_sort"),
            "assigned_username": user["username"],
            "assigned_owner_sub": user["sub"],
            "assigned_owner_sort": owner_sort_key(timestamp, pid),
            "applied": False,
            "rolled_back": False,
        })
    for row in sorted(rows, key=lambda item: str(item.get("pid") or "")):
        owner = str(row.get("owner_sub") or "").strip()
        if not owner or str(row.get("owner_sort") or "").strip():
            continue
        pid = str(row.get("pid") or "").strip()
        timestamp = int(row.get("ts") or 0)
        if not pid or timestamp <= 0:
            raise RuntimeError(f"owned session cannot be indexed safely: {row!r}")
        operations.append({
            "kind": "add_owner_sort",
            "pid": pid,
            "prior_owner_sub": owner,
            "prior_owner_sort": None,
            "assigned_username": None,
            "assigned_owner_sub": owner,
            "assigned_owner_sort": owner_sort_key(timestamp, pid),
            "applied": False,
            "rolled_back": False,
        })
    return {
        "version": 1,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "table": table_name,
        "user_pool_id": user_pool_id,
        "seed": seed,
        "eligible_users": users,
        "ownerless_records": len(ownerless),
        "operations": operations,
        "applied": False,
    }


def apply_manifest(table, manifest: dict, *, checkpoint=None) -> None:
    for operation in manifest["operations"]:
        if operation.get("applied") and not operation.get("rolled_back"):
            continue
        values = {
            ":owner": operation["assigned_owner_sub"],
            ":sort": operation["assigned_owner_sort"],
        }
        if operation["kind"] == "assign_owner":
            table.update_item(
                Key={"pid": operation["pid"]},
                UpdateExpression="SET owner_sub = :owner, owner_sort = :sort",
                ConditionExpression="attribute_not_exists(owner_sub)",
                ExpressionAttributeValues=values,
            )
        else:
            table.update_item(
                Key={"pid": operation["pid"]},
                UpdateExpression="SET owner_sort = :sort",
                ConditionExpression=(
                    "owner_sub = :owner AND attribute_not_exists(owner_sort)"
                ),
                ExpressionAttributeValues=values,
            )
        operation["applied"] = True
        operation["rolled_back"] = False
        if checkpoint:
            checkpoint()


def rollback_manifest(table, manifest: dict, *, checkpoint=None) -> None:
    for operation in reversed(manifest["operations"]):
        if not operation.get("applied") or operation.get("rolled_back"):
            continue
        values = {
            ":owner": operation["assigned_owner_sub"],
            ":sort": operation["assigned_owner_sort"],
        }
        if operation["kind"] == "assign_owner":
            expression = "REMOVE owner_sub, owner_sort"
        else:
            expression = "REMOVE owner_sort"
        table.update_item(
            Key={"pid": operation["pid"]},
            UpdateExpression=expression,
            ConditionExpression="owner_sub = :owner AND owner_sort = :sort",
            ExpressionAttributeValues=values,
        )
        operation["rolled_back"] = True
        if checkpoint:
            checkpoint()


def _write_manifest(path: pathlib.Path, manifest: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")


def main(argv=None) -> int:
    args = _arguments(argv)
    import boto3

    dynamodb = boto3.resource("dynamodb", region_name=args.region)
    table = dynamodb.Table(args.table)
    if args.rollback_manifest:
        manifest = json.loads(args.rollback_manifest.read_text(encoding="utf-8"))
        if not args.apply or args.confirm != ROLLBACK_CONFIRMATION:
            print(json.dumps(manifest, indent=2))
            print(
                f"DRY RUN: add --apply --confirm {ROLLBACK_CONFIRMATION} to roll back",
                file=sys.stderr,
            )
            return 0
        rollback_manifest(
            table,
            manifest,
            checkpoint=lambda: _write_manifest(args.rollback_manifest, manifest),
        )
        manifest["rolled_back_at"] = datetime.now(timezone.utc).isoformat()
        _write_manifest(args.rollback_manifest, manifest)
        print(f"rolled back {len(manifest['operations'])} operations")
        return 0

    cognito = boto3.client("cognito-idp", region_name=args.region)
    users = resolve_users(
        cognito, user_pool_id=args.user_pool_id, usernames=args.users
    )
    manifest = build_manifest(
        scan_sessions(table), users, seed=args.seed,
        table_name=args.table, user_pool_id=args.user_pool_id,
    )
    path = args.manifest or pathlib.Path(
        f"session-owner-manifest-{datetime.now():%Y%m%d-%H%M%S}.json"
    )
    _write_manifest(path, manifest)
    print(f"manifest: {path}")
    print(f"ownerless records: {manifest['ownerless_records']}")
    if not args.apply or args.confirm != APPLY_CONFIRMATION:
        print(
            f"DRY RUN: review the manifest, then use --apply --confirm {APPLY_CONFIRMATION}",
            file=sys.stderr,
        )
        return 0
    apply_manifest(table, manifest, checkpoint=lambda: _write_manifest(path, manifest))
    manifest["applied"] = True
    manifest["applied_at"] = datetime.now(timezone.utc).isoformat()
    _write_manifest(path, manifest)
    print(f"applied {len(manifest['operations'])} operations")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
