"""Composition and FastAPI dependencies for durable session history."""
from __future__ import annotations

from fastapi import HTTPException, Request

from service.core.config import SessionHistorySettings
from service.session_history.adapters import (
    DynamoSessionCatalog,
    DynamoTranscriptStore,
    S3ArtifactStore,
)


def configure_session_history(app) -> None:
    settings = SessionHistorySettings.from_env()
    if not settings.enabled:
        return
    import boto3

    dynamodb = boto3.resource("dynamodb", region_name=settings.region)
    s3 = boto3.client("s3", region_name=settings.region)
    table = dynamodb.Table(settings.table_name)
    app.state.session_catalog = DynamoSessionCatalog(
        table, owner_index=settings.owner_index
    )
    app.state.history_artifacts = S3ArtifactStore(
        s3, bucket=settings.artifact_bucket
    )
    app.state.history_transcripts = DynamoTranscriptStore(
        table, app.state.history_artifacts
    )


def get_session_catalog(request: Request):
    catalog = getattr(request.app.state, "session_catalog", None)
    if catalog is None:
        raise HTTPException(status_code=503, detail="session history is not configured")
    return catalog


def get_history_artifacts(request: Request):
    artifacts = getattr(request.app.state, "history_artifacts", None)
    if artifacts is None:
        raise HTTPException(status_code=503, detail="session history is not configured")
    return artifacts


def get_history_transcripts(request: Request):
    store = getattr(request.app.state, "history_transcripts", None)
    if store is None:
        raise HTTPException(status_code=503, detail="session history is not configured")
    return store
