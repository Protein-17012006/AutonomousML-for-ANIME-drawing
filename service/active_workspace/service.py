"""Active-workspace application logic: open, record, replay, publish, discard."""
from __future__ import annotations

import uuid

from service.active_workspace.models import (
    EVENT_NAMES,
    ActiveWorkspace,
    WorkspaceEvent,
)


class ActiveWorkspaceService:
    def __init__(self, store, publisher=None) -> None:
        self._store = store
        # Promotes a finished workspace to a `complete` catalog session and
        # returns its pid. Injected rather than imported so the domain does not
        # depend on DynamoDB or S3 to be tested.
        self._publisher = publisher

    # --- reading -----------------------------------------------------------

    def active_for(self, owner_sub: str) -> ActiveWorkspace | None:
        return self._store.active_for(owner_sub)

    def get(self, workspace_id: str, owner_sub: str) -> ActiveWorkspace | None:
        return self._store.get_owned(workspace_id, owner_sub)

    def active_response(self, owner_sub: str) -> dict:
        """`{"workspace": null}` when there is nothing open.

        Never a 404 and never a bare object: the client throws
        "Invalid active workspace response." unless the key is present.
        """
        workspace = self.active_for(owner_sub)
        return {"workspace": workspace.to_client_dict() if workspace else None}

    # --- writing -----------------------------------------------------------

    def open_workspace(self, owner_sub: str, *, upload=None) -> ActiveWorkspace:
        self._supersede(owner_sub)
        workspace = ActiveWorkspace(
            workspace_id=uuid.uuid4().hex,
            owner_sub=owner_sub,
            upload=upload,
        )
        self._store.save(workspace)
        self._store.set_active(owner_sub, workspace.workspace_id)
        return workspace

    def append_event(self, workspace_id: str, owner_sub: str, name: str,
                     data: dict) -> WorkspaceEvent | None:
        """Record one frame durably and hand back its sequence.

        Both validations fail loudly on purpose. The client registers listeners
        for five names and ignores everything else, and it drops any payload that
        is not a JSON object — so either mistake would reach a user as an event
        that simply never arrives, with nothing in the log to say why.
        """
        if name not in EVENT_NAMES:
            raise ValueError(
                f"unknown workspace event {name!r}; the client listens for "
                f"{', '.join(EVENT_NAMES)}")
        if not isinstance(data, dict):
            raise ValueError("workspace event data must be a JSON object")
        workspace = self._store.get_owned(workspace_id, owner_sub)
        if workspace is None:
            return None
        event = WorkspaceEvent(sequence=workspace.event_sequence + 1,
                               name=name, data=dict(data))
        workspace.events.append(event)
        self._store.save(workspace)
        return event

    def events_after(self, workspace_id: str, owner_sub: str, *,
                     after: int) -> list[WorkspaceEvent] | None:
        """Every event strictly after `after`, in order. None when not the owner's.

        Strictly-greater matches the client, which discards frames whose
        lastEventId is <= the `after` it sent; returning them anyway would be
        invisible in a browser and would hide an off-by-one until it mattered.
        """
        workspace = self._store.get_owned(workspace_id, owner_sub)
        if workspace is None:
            return None
        return [event for event in workspace.events if event.sequence > after]

    def record_snapshot(self, workspace_id: str, owner_sub: str,
                        snapshot) -> ActiveWorkspace | None:
        """Store the resumable snapshot and bump `revision`.

        The bump is the point: `revision` is the only signal the client has that
        its IndexedDB copy is stale, so a snapshot written without one leaves the
        artist looking at cached frames.
        """
        workspace = self._store.get_owned(workspace_id, owner_sub)
        if workspace is None:
            return None
        workspace.snapshot = snapshot
        workspace.revision += 1
        workspace.state = "complete"
        self._store.save(workspace)
        return workspace

    def publish(self, workspace_id: str, owner_sub: str) -> dict | None:
        """Promote to a durable session. None when it is not this owner's.

        Failure is a first-class outcome, not an exception: the client retries
        through POST /publish and shows the artist "Finish saving your session",
        so a failed publish must leave the workspace alive and retryable.
        """
        workspace = self._store.get_owned(workspace_id, owner_sub)
        if workspace is None:
            return None
        try:
            if self._publisher is None:
                raise RuntimeError("no publisher configured")
            pid = self._publisher(workspace)
        except Exception as exc:                      # noqa: BLE001 — reported, not raised
            workspace.state = "publish_pending"
            self._store.save(workspace)
            outcome = {"published": False, "error": str(exc)}
            self._append(workspace, "publish", outcome)
            return outcome

        workspace.published_pid = str(pid)
        workspace.state = "published"
        self._store.save(workspace)
        outcome = {"published": True, "pid": workspace.published_pid}
        self._append(workspace, "publish", outcome)
        # It STAYS the active workspace. The client branches on `published_pid`
        # — purging its cache on login, opening the saved session on finish — so
        # clearing the slot here would hand it null and leave it nothing to open.
        # A later run supersedes it; see _supersede.
        return outcome

    def record_publication(self, workspace_id: str, owner_sub: str,
                           outcome: dict) -> dict | None:
        """Adopt the publication the RUN already performed.

        `publish_session` runs at the end of every session and is what actually
        writes S3 + DynamoDB and mints the pid. Inventing a second publisher for
        the workspace would file the same work twice under two ids; this takes
        the pid from the system that owns it and reports it in the shape the
        client's `publish` listener expects.
        """
        workspace = self._store.get_owned(workspace_id, owner_sub)
        if workspace is None:
            return None
        pid = outcome.get("pid") if isinstance(outcome, dict) else None
        if not (isinstance(outcome, dict) and outcome.get("published") and pid):
            workspace.state = "publish_pending"
            self._store.save(workspace)
            reported = {"published": False,
                        "error": str((outcome or {}).get("error")
                                     or "publication did not complete")}
        else:
            workspace.published_pid = str(pid)
            workspace.state = "published"
            self._store.save(workspace)
            reported = {"published": True, "pid": workspace.published_pid}
        self._append(workspace, "publish", reported)
        return reported

    def discard(self, workspace_id: str, owner_sub: str) -> bool:
        if self._store.get_owned(workspace_id, owner_sub) is None:
            return False
        self._store.delete(workspace_id, owner_sub)
        return True

    # --- internals ---------------------------------------------------------

    def _append(self, workspace: ActiveWorkspace, name: str, data: dict) -> None:
        workspace.events.append(WorkspaceEvent(
            sequence=workspace.event_sequence + 1, name=name, data=dict(data)))
        self._store.save(workspace)

    def _supersede(self, owner_sub: str) -> None:
        """Make room for a new run without ever losing generated frames.

        A workspace that produced a result is auto-published; one that produced
        nothing is discarded. Publishing an empty run would file a row that
        claims a finished session and contains no work — the same shape as an
        empty run reporting overall_pass: true.
        """
        current = self._store.active_for(owner_sub)
        if current is None:
            return
        # Already published: it was only still here so the client could notice.
        # Publishing again would file the same work as a second session.
        if current.published_pid is None and current.snapshot is not None:
            self.publish(current.workspace_id, owner_sub)
        self._store.delete(current.workspace_id, owner_sub)
