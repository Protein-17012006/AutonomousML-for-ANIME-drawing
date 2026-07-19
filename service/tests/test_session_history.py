"""Durable DynamoDB/S3 session retrieval with Cognito ownership isolation."""
from __future__ import annotations

import json
import time

import boto3
from fastapi.testclient import TestClient
from moto import mock_aws
import pytest

from service.auth_dev_app import app
from service.core.auth import CognitoJwtVerifier
from service.session_history.adapters import DynamoSessionCatalog, S3ArtifactStore


ORIGIN = "https://testserver"
ISSUER = "https://cognito-idp.ap-southeast-1.amazonaws.com/pool-1"
BUCKET = "copilot-history-test"


def _verifier():
    def decode(token: str) -> dict:
        return {
            "iss": ISSUER,
            "sub": token,
            "token_use": "id",
            "aud": "client-1",
            "exp": time.time() + 300,
            "username": token,
        }

    return CognitoJwtVerifier(
        "ap-southeast-1", "pool-1", "client-1", decoder=decode
    )


def _login(sub: str) -> TestClient:
    client = TestClient(app, base_url=ORIGIN)
    response = client.post(
        "/auth/session",
        headers={"Authorization": f"Bearer {sub}", "Origin": ORIGIN},
    )
    assert response.status_code == 204
    return client


def _table(dynamodb):
    return dynamodb.create_table(
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


def _row(pid: str, owner: str | None, timestamp: int) -> dict:
    item = {
        "pid": pid,
        "ts": timestamp,
        "n_pairs": 3,
        "n_autopass": 2,
        "n_corrected": 1,
        "flagged": "[1]",
        "abstained": "[]",
        "needs_key": "[2]",
        "artifact_keys": json.dumps([
            f"artifacts/{pid}/montage.png",
            f"artifacts/{pid}/report.md",
            f"artifacts/{pid}/reconstructed.mp4",
            f"artifacts/other/leak.md",
        ]),
    }
    if owner:
        item.update(
            owner_sub=owner,
            owner_sort=f"CREATED#{timestamp:020d}#{pid}",
        )
    return item


@pytest.fixture
def history_runtime(monkeypatch):
    monkeypatch.setenv("COPILOT_AUTH_REQUIRED", "1")
    old_verifier = getattr(app.state, "auth_verifier", None)
    old_catalog = getattr(app.state, "session_catalog", None)
    old_artifacts = getattr(app.state, "history_artifacts", None)
    app.state.auth_verifier = _verifier()
    with mock_aws():
        dynamodb = boto3.resource("dynamodb", region_name="us-east-1")
        table = _table(dynamodb)
        s3 = boto3.client("s3", region_name="us-east-1")
        s3.create_bucket(Bucket=BUCKET)
        app.state.session_catalog = DynamoSessionCatalog(table)
        app.state.history_artifacts = S3ArtifactStore(s3, bucket=BUCKET)
        yield table, s3
    for name, old in (
        ("auth_verifier", old_verifier),
        ("session_catalog", old_catalog),
        ("history_artifacts", old_artifacts),
    ):
        if old is None:
            try:
                delattr(app.state, name)
            except AttributeError:
                pass
        else:
            setattr(app.state, name, old)


def test_lists_only_current_users_sessions_with_pagination(history_runtime):
    table, _ = history_runtime
    table.put_item(Item=_row("a-old", "user-a", 100))
    table.put_item(Item=_row("a-new", "user-a", 300))
    table.put_item(Item=_row("b-only", "user-b", 400))
    table.put_item(Item=_row("ownerless", None, 500))

    owner = _login("user-a")
    first = owner.get("/sessions?limit=1")
    assert first.status_code == 200
    body = first.json()
    assert [item["pid"] for item in body["items"]] == ["a-new"]
    assert body["next_cursor"]
    assert "owner_sub" not in first.text and "artifacts/a-new" not in first.text

    second = owner.get(
        "/sessions", params={"limit": 1, "cursor": body["next_cursor"]}
    )
    assert second.status_code == 200
    assert [item["pid"] for item in second.json()["items"]] == ["a-old"]
    assert second.json()["next_cursor"] is None


def test_artifact_bytes_are_owned_and_streamed_exactly(history_runtime):
    table, s3 = history_runtime
    table.put_item(Item=_row("a-session", "user-a", 100))
    s3.put_object(
        Bucket=BUCKET,
        Key="artifacts/a-session/report.md",
        Body=b"exact report bytes\n",
        ContentType="text/markdown",
    )
    owner = _login("user-a")
    stranger = _login("user-b")

    response = owner.get("/sessions/a-session/artifacts/report.md")
    assert response.status_code == 200
    assert response.content == b"exact report bytes\n"
    assert response.headers["content-type"].startswith("text/markdown")
    assert stranger.get("/sessions/a-session/artifacts/report.md").status_code == 404
    assert owner.get("/sessions/a-session/artifacts/leak.md").status_code == 404
    assert owner.get("/sessions/a-session/artifacts/missing.png").status_code == 404
    assert owner.get("/sessions/a-session/artifacts/montage.png").status_code == 404


def test_session_history_rejects_anonymous_and_foreign_cursor(history_runtime):
    table, _ = history_runtime
    table.put_item(Item=_row("a-session", "user-a", 100))
    anonymous = TestClient(app, base_url=ORIGIN)
    assert anonymous.get("/sessions").status_code == 401
    owner = _login("user-a")
    foreign_cursor = "Yi1vbmx5"  # urlsafe base64("b-only")
    assert owner.get("/sessions", params={"cursor": foreign_cursor}).status_code == 400
    assert owner.get("/sessions", params={"cursor": "%%%"}).status_code == 400


def test_malformed_artifact_manifest_is_not_exposed(history_runtime):
    table, _ = history_runtime
    row = _row("bad", "user-a", 100)
    row["artifact_keys"] = json.dumps([
        "artifacts/bad/../secret.md",
        "artifacts/other/report.md",
        "artifacts/bad/nested/report.md",
    ])
    table.put_item(Item=row)
    body = _login("user-a").get("/sessions").json()
    assert body["items"][0]["artifacts"] == {
        "montage": None,
        "report": None,
        "video": None,
    }
