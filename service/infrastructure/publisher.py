"""Infrastructure adapter: env-gated AWS publisher (design 'AWS Front Door' §2 Luồng 3): after a session
finishes, push its artifacts to S3 and one record to DynamoDB so results survive box
restarts. OFF unless AWS_PUBLISH=1. Failures degrade to a warning — publishing must
NEVER affect the session (degrade-never-500). boto3 imports lazily: only the box
installs it; the box-free suite injects fake clients."""
from __future__ import annotations

import json
import pathlib
import time
import uuid

from service.core.auth import auth_required
from service.core.config import PublisherSettings

_ARTIFACT_SUFFIXES = {".png", ".md", ".mp4"}


def owner_sort_key(timestamp: int, pid: str) -> str:
    return f"CREATED#{timestamp:020d}#{pid}"


def aws_enabled() -> bool:
    return PublisherSettings.from_env(validate_required=False).enabled


def publish_session(sid, session_dir, result, *, owner_sub=None, clients=None, pid=None):
    """Upload the session's artifacts + write one DynamoDB item. Returns
    {"published", "pid", "s3_keys", "error"}; NEVER raises."""
    s3_keys: list = []
    try:
        settings = PublisherSettings.from_env(require_owner=auth_required())
        if not settings.enabled:
            return {"published": False, "pid": None, "s3_keys": [], "error": None}
        if settings.require_owner and not owner_sub:
            raise RuntimeError("refusing to publish an ownerless authenticated session")
        # PublisherSettings validates both values whenever publishing is enabled.
        bucket = settings.artifact_bucket
        table = settings.sessions_table
        if clients is None:
            import boto3
            clients = {"s3": boto3.client("s3", region_name=settings.region),
                       "ddb": boto3.client("dynamodb", region_name=settings.region)}
        # Opaque storage namespace; durable objects have no public download path.
        pid = pid or uuid.uuid4().hex
        base = pathlib.Path(session_dir)
        for f in sorted(base.iterdir()):
            if f.is_file() and f.suffix.lower() in _ARTIFACT_SUFFIXES:
                key = f"artifacts/{pid}/{f.name}"   # CloudFront passes the full URI as the S3 key
                clients["s3"].upload_file(str(f), bucket, key)
                s3_keys.append(key)
        r = result
        # Derive needs_key indices from pair actions (CopilotResult has no needs_key field)
        needs_key = [getattr(p, "index", i) for i, p in enumerate(r.pairs)
                     if getattr(p, "action", None) == "needs_key"]
        timestamp = int(time.time())
        item = {
            "pid": {"S": pid},
            "sid": {"N": str(sid)},
            "ts": {"N": str(timestamp)},
            "n_pairs": {"N": str(len(r.pairs))},
            "n_autopass": {"N": str(r.n_autopass)},
            "n_corrected": {"N": str(r.n_corrected)},
            "flagged": {"S": json.dumps(list(r.flagged))},
            "abstained": {"S": json.dumps(list(r.abstained))},
            "needs_key": {"S": json.dumps(needs_key)},
            "keys_requested_total": {"N": str(r.keys_requested_total)},
            "artifact_keys": {"S": json.dumps(s3_keys)},
        }
        if owner_sub:
            item["owner_sub"] = {"S": owner_sub}
            item["owner_sort"] = {"S": owner_sort_key(timestamp, pid)}
        clients["ddb"].put_item(TableName=table, Item=item)
        return {"published": True, "pid": pid, "s3_keys": s3_keys, "error": None}
    except Exception as exc:   # noqa: BLE001 — by contract this function never raises
        print(f"[publisher] WARN publish failed (session continues): {exc}", flush=True)
        return {"published": False, "pid": pid, "s3_keys": s3_keys, "error": str(exc)}
