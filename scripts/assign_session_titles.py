"""Assign deterministic friendly titles and complete status to legacy sessions.

Dry-run is the default. Applying or rolling back requires an exact confirmation
phrase. The manifest is checkpointed after every conditional write and is the
only rollback boundary.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import os
import pathlib
import random
import sys
from urllib.parse import urlparse


DEFAULT_SEED = 20260719
APPLY_CONFIRMATION = "ASSIGN_SESSION_TITLES"
ROLLBACK_CONFIRMATION = "ROLLBACK_SESSION_TITLES"
ADJECTIVES = (
    "Amber", "Blue", "Bright", "Crimson", "Distant", "Golden", "Quiet",
    "Silver", "Soft", "Summer", "Velvet", "Winter",
)
NOUNS = (
    "Arc", "Cut", "Frame", "Key", "Motion", "Reel", "Scene", "Shot",
    "Sequence", "Sketch", "Timing", "Tween",
)


def _arguments(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--table", default=os.getenv("AWS_SESSIONS_TABLE"))
    parser.add_argument("--region", default=os.getenv("AWS_REGION", "ap-southeast-1"))
    parser.add_argument("--seed", type=int, default=DEFAULT_SEED)
    parser.add_argument("--manifest", type=pathlib.Path)
    parser.add_argument("--rollback-manifest", type=pathlib.Path)
    parser.add_argument("--checkpoint-s3-uri")
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--confirm", default="")
    args = parser.parse_args(argv)
    if not args.table:
        parser.error("--table or AWS_SESSIONS_TABLE is required")
    if args.rollback_manifest and args.manifest:
        parser.error("--manifest and --rollback-manifest are mutually exclusive")
    return args


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


def build_manifest(rows: list[dict], *, seed: int, table_name: str) -> dict:
    eligible = [
        row for row in rows
        if str(row.get("pid") or "").strip()
        and str(row.get("owner_sub") or "").strip()
        and (not str(row.get("title") or "").strip() or not row.get("status"))
    ]
    eligible.sort(key=lambda row: str(row["pid"]))
    random.Random(seed).shuffle(eligible)
    operations = []
    for index, row in enumerate(eligible, start=1):
        prior_title = str(row.get("title") or "").strip() or None
        prior_status = str(row.get("status") or "").strip() or None
        title = prior_title or (
            f"{ADJECTIVES[(index - 1) % len(ADJECTIVES)]} "
            f"{NOUNS[((index - 1) // len(ADJECTIVES)) % len(NOUNS)]} {index:02d}"
        )
        operations.append({
            "pid": str(row["pid"]),
            "prior_title": prior_title,
            "prior_status": prior_status,
            "assigned_title": title,
            "assigned_status": prior_status or "complete",
            "add_title": prior_title is None,
            "add_status": prior_status is None,
            "applied": False,
            "rolled_back": False,
        })
    return {
        "version": 1,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "table": table_name,
        "seed": seed,
        "operations": operations,
        "applied": False,
    }


def apply_manifest(table, manifest: dict, *, checkpoint=None) -> None:
    for operation in manifest["operations"]:
        if operation.get("applied") and not operation.get("rolled_back"):
            continue
        sets, conditions, values = [], ["attribute_exists(owner_sub)"], {}
        if operation["add_title"]:
            sets.append("title = :title")
            conditions.append("attribute_not_exists(title)")
            values[":title"] = operation["assigned_title"]
        if operation["add_status"]:
            sets.append("#status = :status")
            conditions.append("attribute_not_exists(#status)")
            values[":status"] = operation["assigned_status"]
        request = dict(
            Key={"pid": operation["pid"]},
            UpdateExpression="SET " + ", ".join(sets),
            ConditionExpression=" AND ".join(conditions),
            ExpressionAttributeValues=values,
        )
        if operation["add_status"]:
            request["ExpressionAttributeNames"] = {"#status": "status"}
        table.update_item(**request)
        operation["applied"] = True
        operation["rolled_back"] = False
        if checkpoint:
            checkpoint()


def rollback_manifest(table, manifest: dict, *, checkpoint=None) -> None:
    for operation in reversed(manifest["operations"]):
        if not operation.get("applied") or operation.get("rolled_back"):
            continue
        removes, conditions, values = [], [], {}
        if operation["add_title"]:
            removes.append("title")
            conditions.append("title = :title")
            values[":title"] = operation["assigned_title"]
        if operation["add_status"]:
            removes.append("#status")
            conditions.append("#status = :status")
            values[":status"] = operation["assigned_status"]
        request = dict(
            Key={"pid": operation["pid"]},
            UpdateExpression="REMOVE " + ", ".join(removes),
            ConditionExpression=" AND ".join(conditions),
            ExpressionAttributeValues=values,
        )
        if operation["add_status"]:
            request["ExpressionAttributeNames"] = {"#status": "status"}
        table.update_item(**request)
        operation["rolled_back"] = True
        if checkpoint:
            checkpoint()


def _write_manifest(path: pathlib.Path, manifest: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")


def _s3_location(uri: str) -> tuple[str, str]:
    parsed = urlparse(uri)
    if parsed.scheme != "s3" or not parsed.netloc or not parsed.path.lstrip("/"):
        raise ValueError("checkpoint URI must be s3://bucket/key")
    return parsed.netloc, parsed.path.lstrip("/")


def main(argv=None) -> int:
    args = _arguments(argv)
    import boto3

    table = boto3.resource("dynamodb", region_name=args.region).Table(args.table)
    s3 = boto3.client("s3", region_name=args.region)
    path = args.rollback_manifest or args.manifest or pathlib.Path(
        f"session-title-manifest-{datetime.now():%Y%m%d-%H%M%S}.json"
    )
    if args.rollback_manifest:
        manifest = json.loads(path.read_text(encoding="utf-8"))
    else:
        manifest = build_manifest(
            scan_sessions(table), seed=args.seed, table_name=args.table
        )
        _write_manifest(path, manifest)

    def checkpoint():
        _write_manifest(path, manifest)
        if args.checkpoint_s3_uri:
            bucket, key = _s3_location(args.checkpoint_s3_uri)
            s3.put_object(
                Bucket=bucket,
                Key=key,
                Body=(json.dumps(manifest, indent=2) + "\n").encode("utf-8"),
                ContentType="application/json",
            )

    print(f"manifest: {path}")
    print(f"operations: {len(manifest['operations'])}")
    confirmation = ROLLBACK_CONFIRMATION if args.rollback_manifest else APPLY_CONFIRMATION
    if not args.apply or args.confirm != confirmation:
        print(
            f"DRY RUN: review the manifest, then use --apply --confirm {confirmation}",
            file=sys.stderr,
        )
        return 0
    if args.rollback_manifest:
        rollback_manifest(table, manifest, checkpoint=checkpoint)
        manifest["rolled_back_at"] = datetime.now(timezone.utc).isoformat()
    else:
        apply_manifest(table, manifest, checkpoint=checkpoint)
        manifest["applied"] = True
        manifest["applied_at"] = datetime.now(timezone.utc).isoformat()
    checkpoint()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
