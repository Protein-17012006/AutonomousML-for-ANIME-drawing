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
from urllib.parse import urlsplit

from service.core.auth import auth_required
from service.core.config import PublisherSettings
from service.session_history.models import WorkspaceSnapshot, WorkspaceUpload
from service.sessions.schemas import PairEvent, ResultEvent

_ARTIFACT_SUFFIXES = {".png", ".md", ".mp4"}


def owner_sort_key(timestamp: int, pid: str) -> str:
    return f"CREATED#{timestamp:020d}#{pid}"


def aws_enabled() -> bool:
    return PublisherSettings.from_env(validate_required=False).enabled


def _basename(value) -> str | None:
    if not isinstance(value, str) or not value:
        return None
    name = pathlib.PurePosixPath(urlsplit(value).path).name
    return name or None


def _workspace_snapshot(outcome, uploaded_names: set[str], workspace_input) -> WorkspaceSnapshot:
    result = getattr(outcome, "result", outcome)

    def available(value):
        name = _basename(value)
        return name if name in uploaded_names else None

    pair_mids = {
        str(index): name
        for index, value in (getattr(outcome, "pair_mids", {}) or {}).items()
        if (name := available(value)) is not None
    }
    key_urls = {
        str(index): name
        for index, value in (getattr(outcome, "key_urls", {}) or {}).items()
        if (name := available(value)) is not None
    }
    explanations = json.loads(json.dumps(getattr(outcome, "explanations", {}) or {}))
    for explanation in explanations.values():
        if isinstance(explanation, dict) and "annotated_url" in explanation:
            explanation["annotated_url"] = available(explanation["annotated_url"])
    artifact_names = {
        "montage": "montage.png",
        "report": "report.md",
        "video": "reconstructed.mp4",
    }
    artifacts = {
        field: name for field, name in artifact_names.items() if name in uploaded_names
    }
    pairs = []
    for pair in result.pairs:
        try:
            event = PairEvent.from_pair(
                pair, mid_url=pair_mids.get(str(pair.index))
            )
        except AttributeError:
            event = PairEvent(
                index=pair.index,
                action=pair.action,
                keys_requested=getattr(pair, "keys_requested", 0),
                mid_url=pair_mids.get(str(pair.index)),
            )
        pairs.append(event)
    final = ResultEvent.from_result(
        result,
        artifacts=artifacts,
        explanations=explanations,
        pair_mids=pair_mids,
        key_urls=key_urls,
        sampling=dict(getattr(outcome, "sampling", {}) or {}),
        csq=getattr(outcome, "csq", None),
        qa_degraded=bool(getattr(outcome, "qa_degraded", False)),
    )
    upload = WorkspaceUpload.model_validate(
        workspace_input
        or {"mode": "frames", "label": "Uploaded media", "filenames": []}
    )
    return WorkspaceSnapshot(
        schema_version=1,
        upload=upload,
        pairs=pairs,
        result=final,
    )


def publish_session(
    sid,
    session_dir,
    outcome,
    *,
    owner_sub=None,
    clients=None,
    pid=None,
    workspace_input=None,
):
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
        requested_pid = pid
        pid = requested_pid or uuid.uuid4().hex
        base = pathlib.Path(session_dir)
        artifact_keys: list[str] = []
        for f in sorted(base.iterdir()):
            if f.is_file() and f.suffix.lower() in _ARTIFACT_SUFFIXES:
                key = f"artifacts/{pid}/{f.name}"   # CloudFront passes the full URI as the S3 key
                clients["s3"].upload_file(str(f), bucket, key)
                s3_keys.append(key)
                artifact_keys.append(key)
        snapshot = _workspace_snapshot(
            outcome,
            {pathlib.PurePosixPath(key).name for key in artifact_keys},
            workspace_input,
        )
        snapshot_key = f"artifacts/{pid}/workspace.v1.json"
        clients["s3"].put_object(
            Bucket=bucket,
            Key=snapshot_key,
            Body=snapshot.model_dump_json().encode("utf-8"),
            ContentType="application/json",
        )
        s3_keys.append(snapshot_key)
        r = getattr(outcome, "result", outcome)
        # Derive needs_key indices from pair actions (CopilotResult has no needs_key field)
        needs_key = [getattr(p, "index", i) for i, p in enumerate(r.pairs)
                     if getattr(p, "action", None) == "needs_key"]
        timestamp = int(time.time())
        common_item = {
            "pid": {"S": pid},
            "sid": {"N": str(sid)},
            "updated_at": {"N": str(timestamp)},
            "status": {"S": "complete"},
            "n_pairs": {"N": str(len(r.pairs))},
            "n_autopass": {"N": str(r.n_autopass)},
            "n_corrected": {"N": str(r.n_corrected)},
            "flagged": {"S": json.dumps(list(r.flagged))},
            "abstained": {"S": json.dumps(list(r.abstained))},
            "needs_key": {"S": json.dumps(needs_key)},
            "keys_requested_total": {"N": str(r.keys_requested_total)},
            "artifact_keys": {"S": json.dumps(artifact_keys)},
            "snapshot_key": {"S": snapshot_key},
            "snapshot_version": {"N": "1"},
        }
        if requested_pid:
            if not owner_sub:
                raise RuntimeError("refusing to complete a draft without its owner")
            update_fields = {
                key: value for key, value in common_item.items() if key != "pid"
            }
            values = {
                f":{key}": value for key, value in update_fields.items()
            }
            values.update({":owner": {"S": owner_sub}, ":draft": {"S": "draft"}})
            clients["ddb"].update_item(
                TableName=table,
                Key={"pid": {"S": pid}},
                UpdateExpression="SET " + ", ".join(
                    f"#{key} = :{key}" if key == "status" else f"{key} = :{key}"
                    for key in update_fields
                ),
                ConditionExpression="owner_sub = :owner AND #status = :draft",
                ExpressionAttributeNames={"#status": "status"},
                ExpressionAttributeValues=values,
            )
        else:
            item = dict(common_item)
            item.update({
                "ts": {"N": str(timestamp)},
                "title": {"S": "Untitled session"},
            })
            if owner_sub:
                item["owner_sub"] = {"S": owner_sub}
                item["owner_sort"] = {"S": owner_sort_key(timestamp, pid)}
            clients["ddb"].put_item(TableName=table, Item=item)
        return {"published": True, "pid": pid, "s3_keys": s3_keys, "error": None}
    except Exception as exc:   # noqa: BLE001 — by contract this function never raises
        print(f"[publisher] WARN publish failed (session continues): {exc}", flush=True)
        return {"published": False, "pid": pid, "s3_keys": s3_keys, "error": str(exc)}
