"""Validated HTTP and application models for durable session history."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from pydantic import BaseModel, Field, field_validator

from service.sessions.schemas import PairEvent, ResultEvent


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
    title: str
    status: Literal["draft", "complete"]
    created_at: str
    updated_at: str
    workspace_available: bool = False
    summary: SessionSummaryCounts
    artifacts: ArtifactLinks


class SessionListResponse(BaseModel):
    items: list[SessionSummary]
    next_cursor: str | None = None


class SessionTitleRequest(BaseModel):
    title: str = Field(min_length=1, max_length=80)

    @field_validator("title")
    @classmethod
    def normalize_title(cls, value: str) -> str:
        normalized = " ".join(value.split())
        if not normalized or len(normalized) > 80:
            raise ValueError("title must contain between 1 and 80 characters")
        if any(ord(char) < 32 or ord(char) == 127 for char in normalized):
            raise ValueError("title must not contain control characters")
        return normalized


class WorkspaceUpload(BaseModel):
    mode: Literal["frames", "video"]
    label: str
    filenames: list[str] = Field(default_factory=list)


class WorkspaceSnapshot(BaseModel):
    schema_version: Literal[1]
    upload: WorkspaceUpload
    pairs: list[PairEvent]
    result: ResultEvent


class QaTranscriptTurn(BaseModel):
    turn_id: str
    question: str
    answer: str
    grounded: bool
    answered_at: str


class QaTranscriptSnapshot(BaseModel):
    schema_version: Literal[1]
    pid: str
    turns: list[QaTranscriptTurn] = Field(default_factory=list)


class WorkspaceHydration(WorkspaceSnapshot):
    """Owner-authorized workspace response, enriched with a separate transcript."""

    qa: list[QaTranscriptTurn] = Field(default_factory=list)


@dataclass(frozen=True)
class PublishedSession:
    summary: SessionSummary
    owner_sub: str
    artifact_keys: dict[str, str]
    owner_sort: str
    snapshot_key: str | None = None
    snapshot_version: int | None = None
    message_snapshot_key: str | None = None
    message_version: int | None = None


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
