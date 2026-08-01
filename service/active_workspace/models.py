"""Validated, non-durable models for the active-workspace recovery layer."""
from __future__ import annotations

from typing import Any, Literal
from pydantic import BaseModel, Field

WorkspaceState = Literal["generating", "ready", "publish_pending", "published", "failed"]


class AssetRecord(BaseModel):
    name: str
    kind: str
    size: int = 0
    sha256: str = ""


class JournalEvent(BaseModel):
    sequence: int
    name: Literal["workspace", "pair", "result", "error", "publish"]
    data: dict[str, Any]


class ActiveWorkspaceManifest(BaseModel):
    schema_version: Literal[1] = 1
    workspace_id: str
    owner_hash: str
    state: WorkspaceState = "generating"
    created_at: int
    updated_at: int
    expires_at: int
    revision: int = 0
    event_sequence: int = 0
    history_pid: str | None = None
    reservation_bytes: int
    assets: list[AssetRecord] = Field(default_factory=list)
    events: list[JournalEvent] = Field(default_factory=list)
    snapshot: dict[str, Any] = Field(default_factory=dict)
    published_pid: str | None = None


class ActiveWorkspaceResponse(BaseModel):
    workspace: ActiveWorkspaceManifest | None = None
