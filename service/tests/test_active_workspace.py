"""The active workspace: a run that survives a reload.

The contract under test is NOT ours to choose. It was extracted field-by-field
from the JS the site actually serves, because the frontend calling
`/active-workspace` exists in no commit of either repo — only in the deployed
bundle. Every assertion here mirrors something the shipped client does:
it throws unless `workspace_id` and `state` are strings, it discards SSE frames
whose `lastEventId` is `<= after`, it treats `publish.published !== true` as
`publish_pending`, and it reads `published_pid` to decide the run is over.
"""
from service.active_workspace.models import WorkspaceEvent
from service.active_workspace.store import InMemoryActiveWorkspaceStore
from service.active_workspace.service import ActiveWorkspaceService
from service.session_history.models import (
    WorkspaceSnapshot,
    WorkspaceUpload,
)
from service.sessions.schemas import PairEvent, ResultEvent


def _pair(index: int) -> PairEvent:
    return PairEvent(index=index, action="fill", qa="pass", keys_requested=0)


def _result(n_autopass: int = 2) -> ResultEvent:
    return ResultEvent(n_autopass=n_autopass, n_corrected=0, keys_requested_total=0,
                       flagged=[], abstained=[], needs_key=[], artifacts={})


def _snapshot() -> WorkspaceSnapshot:
    return WorkspaceSnapshot(
        schema_version=1,
        upload=WorkspaceUpload(mode="frames", label="3 keyframes",
                               filenames=["0.png", "1.png", "2.png"]),
        pairs=[_pair(0), _pair(1)],
        result=_result(),
    )


def _service() -> ActiveWorkspaceService:
    return ActiveWorkspaceService(InMemoryActiveWorkspaceStore())


# --- B1: the per-owner active pointer -------------------------------------------

def test_an_owner_with_no_run_has_no_active_workspace():
    assert _service().active_for("owner-1") is None


def test_opening_a_workspace_makes_it_the_owners_active_one():
    svc = _service()
    opened = svc.open_workspace("owner-1", upload=_snapshot().upload)
    found = svc.active_for("owner-1")
    assert found is not None
    assert found.workspace_id == opened.workspace_id
    assert found.state == "draft"


def test_the_client_required_fields_are_present_and_are_strings():
    """The shipped client throws "Invalid active workspace." unless both of
    these are strings, so this is the one shape failure a user would SEE."""
    svc = _service()
    svc.open_workspace("owner-1", upload=_snapshot().upload)
    body = svc.active_response("owner-1")
    workspace = body["workspace"]
    assert isinstance(workspace["workspace_id"], str)
    assert isinstance(workspace["state"], str)


def test_an_owner_never_has_two_active_workspaces():
    svc = _service()
    first = svc.open_workspace("owner-1", upload=_snapshot().upload)
    second = svc.open_workspace("owner-1", upload=_snapshot().upload)
    active = svc.active_for("owner-1")
    assert active.workspace_id == second.workspace_id
    assert first.workspace_id != second.workspace_id


def test_one_owners_run_never_appears_as_anothers():
    svc = _service()
    svc.open_workspace("owner-1", upload=_snapshot().upload)
    assert svc.active_for("owner-2") is None


def test_active_response_for_an_owner_with_nothing_is_a_null_workspace():
    """`{"workspace": null}` is a shape the client handles; a bare 404 or a
    missing key is not — it throws "Invalid active workspace response."."""
    assert _service().active_response("owner-1") == {"workspace": None}


# --- B2: the durable event log and exact replay ---------------------------------

def test_sequences_start_at_one_and_increase_by_one():
    """`after=0` is what a fresh client sends, and it must not hide event 1."""
    svc = _service()
    ws = svc.open_workspace("owner-1", upload=_snapshot().upload)
    for index in range(3):
        svc.append_event(ws.workspace_id, "owner-1", "pair", _pair(index).model_dump())
    events = svc.events_after(ws.workspace_id, "owner-1", after=0)
    assert [event.sequence for event in events] == [1, 2, 3]


def test_event_sequence_reports_the_last_issued_sequence():
    svc = _service()
    ws = svc.open_workspace("owner-1", upload=_snapshot().upload)
    svc.append_event(ws.workspace_id, "owner-1", "pair", _pair(0).model_dump())
    svc.append_event(ws.workspace_id, "owner-1", "pair", _pair(1).model_dump())
    assert svc.active_for("owner-1").event_sequence == 2


def test_replay_after_n_drops_nothing_and_repeats_nothing():
    """The client reconnects 1s after onerror resending after=<last seen>. A gap
    loses a pair from the artist's board; a repeat is filtered client-side but
    proves the sequence is not authoritative."""
    svc = _service()
    ws = svc.open_workspace("owner-1", upload=_snapshot().upload)
    for index in range(5):
        svc.append_event(ws.workspace_id, "owner-1", "pair", _pair(index).model_dump())

    first_leg = svc.events_after(ws.workspace_id, "owner-1", after=0)[:2]
    resumed = svc.events_after(ws.workspace_id, "owner-1",
                               after=first_leg[-1].sequence)

    seen = [event.sequence for event in first_leg] + [e.sequence for e in resumed]
    assert seen == [1, 2, 3, 4, 5]


def test_replay_after_the_last_event_is_empty_not_an_error():
    svc = _service()
    ws = svc.open_workspace("owner-1", upload=_snapshot().upload)
    svc.append_event(ws.workspace_id, "owner-1", "result", _result().model_dump())
    assert svc.events_after(ws.workspace_id, "owner-1", after=1) == []


def test_only_the_five_names_the_client_listens_for_are_accepted():
    """The client registers listeners for exactly five names. Emitting any other
    is indistinguishable from emitting nothing, so it must fail loudly here."""
    import pytest

    svc = _service()
    ws = svc.open_workspace("owner-1", upload=_snapshot().upload)
    with pytest.raises(ValueError):
        svc.append_event(ws.workspace_id, "owner-1", "progress", {"pct": 10})


def test_event_data_must_be_a_json_object():
    """The client does `if (typeof l !== "object" || l === null ||
    Array.isArray(l)) return;` — a list payload is silently dropped on arrival."""
    import pytest

    svc = _service()
    ws = svc.open_workspace("owner-1", upload=_snapshot().upload)
    with pytest.raises(ValueError):
        svc.append_event(ws.workspace_id, "owner-1", "pair", [1, 2, 3])


def test_events_of_another_owner_are_not_readable():
    svc = _service()
    ws = svc.open_workspace("owner-1", upload=_snapshot().upload)
    svc.append_event(ws.workspace_id, "owner-1", "pair", _pair(0).model_dump())
    assert svc.events_after(ws.workspace_id, "owner-2", after=0) is None


# --- B3: publish, discard, and superseding an open workspace ---------------------

class _Publisher:
    """Stands in for promoting a draft to a `complete` catalog session."""

    def __init__(self, pid="pid-1", fail_times=0):
        self.pid, self.fail_times, self.calls = pid, fail_times, 0
        self.published_ids: list[str] = []

    def __call__(self, workspace):
        self.calls += 1
        self.published_ids.append(workspace.workspace_id)
        if self.calls <= self.fail_times:
            raise RuntimeError("S3 write failed")
        return self.pid


def _service_with(publisher):
    return ActiveWorkspaceService(InMemoryActiveWorkspaceStore(), publisher=publisher)


def _finished(svc, owner="owner-1"):
    ws = svc.open_workspace(owner, upload=_snapshot().upload)
    svc.record_snapshot(ws.workspace_id, owner, _snapshot())
    return ws


def test_recording_a_snapshot_bumps_the_revision():
    """`revision` is the ONLY signal the client has that its IndexedDB copy is
    stale; if it never moves the client serves the artist cached frames."""
    svc = _service()
    ws = svc.open_workspace("owner-1", upload=_snapshot().upload)
    before = svc.active_for("owner-1").revision
    svc.record_snapshot(ws.workspace_id, "owner-1", _snapshot())
    assert svc.active_for("owner-1").revision == before + 1


def test_publish_promotes_the_run_and_reports_the_pid():
    publisher = _Publisher(pid="pid-42")
    svc = _service_with(publisher)
    ws = _finished(svc)
    assert svc.publish(ws.workspace_id, "owner-1") == {"published": True,
                                                       "pid": "pid-42"}
    assert svc.active_for("owner-1").state == "published"


def test_publish_emits_a_publish_event_the_stream_can_deliver():
    """A client watching the stream learns of publication through this event —
    it closes the EventSource on `published === true`."""
    svc = _service_with(_Publisher(pid="pid-42"))
    ws = _finished(svc)
    svc.publish(ws.workspace_id, "owner-1")
    events = svc.events_after(ws.workspace_id, "owner-1", after=0)
    assert events[-1].name == "publish"
    assert events[-1].data == {"published": True, "pid": "pid-42"}


def test_a_failed_publish_is_retryable_and_says_so():
    publisher = _Publisher(pid="pid-7", fail_times=1)
    svc = _service_with(publisher)
    ws = _finished(svc)

    first = svc.publish(ws.workspace_id, "owner-1")
    assert first["published"] is False and first["error"]
    assert svc.active_for("owner-1").state == "publish_pending"

    second = svc.publish(ws.workspace_id, "owner-1")
    assert second == {"published": True, "pid": "pid-7"}


def test_discard_removes_the_workspace():
    svc = _service()
    ws = _finished(svc)
    assert svc.discard(ws.workspace_id, "owner-1") is True
    assert svc.active_response("owner-1") == {"workspace": None}


def test_another_owner_cannot_discard_or_publish_it():
    svc = _service_with(_Publisher())
    ws = _finished(svc)
    assert svc.discard(ws.workspace_id, "owner-2") is False
    assert svc.publish(ws.workspace_id, "owner-2") is None
    assert svc.active_for("owner-1") is not None


def test_a_new_run_auto_publishes_the_previous_finished_workspace():
    """Team-lead decision 2026-08-01: superseding must never lose frames the
    artist already paid for, even if they dismissed the resume dialog."""
    publisher = _Publisher(pid="pid-old")
    svc = _service_with(publisher)
    old = _finished(svc)
    svc.open_workspace("owner-1", upload=_snapshot().upload)
    # Asserted through the publisher, not the record: the superseded workspace is
    # removed once its work is safely in history, so there is nothing left to read.
    assert publisher.published_ids == [old.workspace_id]


def test_a_new_run_discards_a_previous_workspace_that_produced_nothing():
    """An abandoned run has no result. Filing it as a finished session is the
    empty-run-reports-success failure, and this is where it would enter."""
    publisher = _Publisher()
    svc = _service_with(publisher)
    empty = svc.open_workspace("owner-1", upload=_snapshot().upload)
    svc.open_workspace("owner-1", upload=_snapshot().upload)
    assert publisher.calls == 0
    assert svc.get(empty.workspace_id, "owner-1") is None


def test_a_published_workspace_is_still_returned_so_the_client_can_react():
    """On login the client branches `published_pid ? purgeCache() : showResume()`,
    and on finish it calls openSession(published_pid). Clearing the slot on
    publish returns null instead, and the client has nothing left to open."""
    svc = _service_with(_Publisher(pid="pid-3"))
    ws = _finished(svc)
    svc.publish(ws.workspace_id, "owner-1")
    assert svc.active_response("owner-1")["workspace"]["published_pid"] == "pid-3"


def test_superseding_an_already_published_workspace_does_not_publish_it_twice():
    """It lingers until the client acknowledges it or a new run replaces it. A
    second publish would file the same work as a second session."""
    publisher = _Publisher(pid="pid-3")
    svc = _service_with(publisher)
    ws = _finished(svc)
    svc.publish(ws.workspace_id, "owner-1")
    svc.open_workspace("owner-1", upload=_snapshot().upload)
    assert publisher.calls == 1
    assert svc.get(ws.workspace_id, "owner-1") is None


class _DeleteDeniedStore(InMemoryActiveWorkspaceStore):
    """A store that cannot delete — exactly what production was.

    The box's IAM identity held GetItem/PutItem/UpdateItem on `copilot_sessions`
    but NOT DeleteItem, because before the active workspace nothing ever removed
    a session row. `_supersede` deletes the run it replaces, so from the SECOND
    run onward `open_workspace` raised, `streaming.py` swallowed it, and the run
    proceeded with no workspace at all — leaving the previous, already-published
    workspace in the pointer. Resume then offered the artist a run they had
    already finished, and it was invisible: every layer degraded quietly.
    """

    def delete(self, workspace_id: str, owner_sub: str) -> None:
        raise RuntimeError("AccessDeniedException: dynamodb:DeleteItem")


def test_a_new_run_still_gets_a_workspace_when_the_old_one_cannot_be_deleted():
    svc = ActiveWorkspaceService(_DeleteDeniedStore())
    first = svc.open_workspace("owner-1", upload=_snapshot().upload)

    second = svc.open_workspace("owner-1", upload=_snapshot().upload)

    assert second.workspace_id != first.workspace_id
    active = svc.active_for("owner-1")
    assert active is not None and active.workspace_id == second.workspace_id
    assert active.state == "draft"
