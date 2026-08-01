"""Data for the active workspace, and the client behaviour each field feeds.

Every field below was read out of the deployed bundle, not chosen. The notes say
what the shipped client does with it, because that — not our preference — is what
makes a field required.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal, Optional

from pydantic import BaseModel

from service.session_history.models import WorkspaceSnapshot, WorkspaceUpload


# The client sets "publish_pending" itself when a publish event says published is
# not true, and treats "published" as terminal. "draft" and "complete" mirror the
# catalog's two statuses.
WorkspaceState = Literal["draft", "complete", "publish_pending", "published"]

# The client registers exactly these five listeners on the EventSource. An event
# with any other name is never delivered, so emitting one is the same as silence.
EVENT_NAMES = ("workspace", "pair", "result", "error", "publish")


class WorkspaceAsset(BaseModel):
    """One uploaded input, kept so a resume on ANOTHER device can rebuild the
    artist's original File objects — IndexedDB holds nothing there."""

    kind: Literal["input-key", "input-video"]
    name: str


@dataclass(frozen=True)
class WorkspaceEvent:
    """One durable SSE frame. `sequence` becomes the SSE `id:` field, which the
    client reads back as `lastEventId` and uses to drop anything <= `after`."""

    sequence: int
    name: str
    data: dict


@dataclass
class ActiveWorkspace:
    workspace_id: str
    owner_sub: str
    state: str = "draft"
    # Bumped on every snapshot write. The client compares it against its cached
    # copy to decide whether to rehydrate from `snapshot` or trust IndexedDB.
    revision: int = 0
    published_pid: Optional[str] = None
    snapshot: Optional[WorkspaceSnapshot] = None
    upload: Optional[WorkspaceUpload] = None
    assets: list[WorkspaceAsset] = field(default_factory=list)
    artifact_urls: dict[str, str] = field(default_factory=dict)
    events: list[WorkspaceEvent] = field(default_factory=list)

    @property
    def event_sequence(self) -> int:
        """The last sequence issued. The client resumes the stream from here."""
        return self.events[-1].sequence if self.events else 0

    def to_client_dict(self) -> dict:
        """The `workspace` object exactly as the deployed client parses it.

        `workspace_id` and `state` MUST be strings: the client throws
        "Invalid active workspace." otherwise, which surfaces as a red banner.
        """
        return {
            "workspace_id": self.workspace_id,
            "state": self.state,
            "revision": self.revision,
            "event_sequence": self.event_sequence,
            "published_pid": self.published_pid,
            "snapshot": self.snapshot.model_dump() if self.snapshot else None,
            "assets": [asset.model_dump() for asset in self.assets],
            "artifact_urls": dict(self.artifact_urls),
        }
