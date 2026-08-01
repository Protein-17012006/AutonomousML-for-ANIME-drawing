from service.active_workspace.service import ActiveWorkspaceService
from service.core.config import ActiveWorkspaceSettings


def _store(tmp_path):
    return ActiveWorkspaceService(
        ActiveWorkspaceSettings(
            root=tmp_path,
            ttl_seconds=60,
            workspace_bytes=1024,
            global_bytes=8192,
            free_reserve_bytes=0,
        )
    )


def test_published_workspace_compacts_to_a_receipt(tmp_path):
    store = _store(tmp_path)
    owner = "artist-sub"
    created = store.create_or_get(owner, history_pid="draft-pid")
    store.append_event(owner, "workspace", {"large": "recovery-state"})
    store.set_state(owner, "ready", snapshot={"pairs": [{"index": 0}]})

    receipt = store.set_state(owner, "published", published_pid="durable-pid")

    assert receipt.published_pid == "durable-pid"
    assert receipt.snapshot == {}
    assert receipt.events == []
    assert receipt.assets == []
    assert receipt.history_pid is None
    assert receipt.reservation_bytes == 0
    active_dir = tmp_path / store.owner_hash(owner) / "active"
    assert not (active_dir / "inputs").exists()
    assert not (active_dir / "generated").exists()

    final = store.append_event(owner, "publish", {"published": True, "pid": "durable-pid"})
    persisted = store.get(owner)
    assert persisted is not None
    assert final.sequence > created.event_sequence
    assert [event.name for event in persisted.events] == ["publish"]
