"""Infrastructure adapter: env-gated AWS publisher (design 'AWS Front Door' §2 Luồng 3): after a session
finishes, push its artifacts to S3 and one record to DynamoDB so results survive box
restarts. OFF unless AWS_PUBLISH=1. Failures degrade to a warning — publishing must
NEVER affect the session (degrade-never-500). boto3 imports lazily: only the box
installs it; the box-free suite injects fake clients."""
from __future__ import annotations

import json
import os
import pathlib
import time
import uuid

_ARTIFACT_SUFFIXES = {".png", ".md", ".mp4"}


def aws_enabled() -> bool:
    return os.environ.get("AWS_PUBLISH") == "1"


def publish_session(sid, session_dir, result, *, clients=None, pid=None):
    """Upload the session's artifacts + write one DynamoDB item. Returns
    {"published", "pid", "s3_keys", "error"}; NEVER raises."""
    if not aws_enabled():
        return {"published": False, "pid": None, "s3_keys": [], "error": None}
    s3_keys: list = []
    try:
        bucket = os.environ["AWS_ARTIFACT_BUCKET"]
        table = os.environ["AWS_SESSIONS_TABLE"]
        region = os.environ.get("AWS_REGION", "ap-southeast-1")
        if clients is None:
            import boto3
            clients = {"s3": boto3.client("s3", region_name=region),
                       "ddb": boto3.client("dynamodb", region_name=region)}
        pid = pid or uuid.uuid4().hex     # unguessable: /artifacts/* skips ALB auth by design
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
        clients["ddb"].put_item(TableName=table, Item={
            "pid": {"S": pid},
            "sid": {"N": str(sid)},
            "ts": {"N": str(int(time.time()))},
            "n_pairs": {"N": str(len(r.pairs))},
            "n_autopass": {"N": str(r.n_autopass)},
            "n_corrected": {"N": str(r.n_corrected)},
            "flagged": {"S": json.dumps(list(r.flagged))},
            "abstained": {"S": json.dumps(list(r.abstained))},
            "needs_key": {"S": json.dumps(needs_key)},
            "keys_requested_total": {"N": str(r.keys_requested_total)},
            "artifact_keys": {"S": json.dumps(s3_keys)},
        })
        return {"published": True, "pid": pid, "s3_keys": s3_keys, "error": None}
    except Exception as exc:   # noqa: BLE001 — by contract this function never raises
        print(f"[publisher] WARN publish failed (session continues): {exc}", flush=True)
        return {"published": False, "pid": pid, "s3_keys": s3_keys, "error": str(exc)}
