"""Validated HTTP and application models for durable session history."""
from __future__ import annotations

from dataclasses import dataclass

from pydantic import BaseModel


class ArtifactLinks(BaseModel):
    montage: str | None = None
    report: str | None = None
    video: str | None = None


class SessionSummaryCounts(BaseModel):
    n_pairs: int = 0
    n_autopass: int = 0
    n_corrected: int = 0
    flagged: int = 0
    abstained: int = 0
    needs_key: int = 0


class SessionSummary(BaseModel):
    pid: str
    created_at: str
    summary: SessionSummaryCounts
    artifacts: ArtifactLinks


class SessionListResponse(BaseModel):
    items: list[SessionSummary]
    next_cursor: str | None = None


@dataclass(frozen=True)
class PublishedSession:
    summary: SessionSummary
    owner_sub: str
    artifact_keys: dict[str, str]
    owner_sort: str


@dataclass(frozen=True)
class SessionPage:
    items: list[PublishedSession]
    next_cursor: str | None


@dataclass(frozen=True)
class StoredArtifact:
    body: object
    content_type: str | None
    content_length: int | None
    filename: str
