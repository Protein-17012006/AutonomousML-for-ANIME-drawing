"""BoundedSessionStore: cap, oldest-first eviction, temp-dir + state cleanup."""
import os
import tempfile

from service.sessions.store import BoundedSessionStore


def _mkdirs(n):
    return [tempfile.mkdtemp(prefix=f"bss_test_{i}_") for i in range(n)]


def test_evicts_oldest_and_rmtrees_its_dir():
    state = {}
    store = BoundedSessionStore(cap=2, state=state)
    d = _mkdirs(3)
    for sid, path in enumerate(d):
        store[sid] = path
        state[sid] = {"result": sid}
    assert set(store) == {1, 2}                 # oldest (0) evicted
    assert not os.path.isdir(d[0])              # its temp dir removed
    assert os.path.isdir(d[1]) and os.path.isdir(d[2])
    assert set(state) == {1, 2}                 # companion state pruned too


def test_under_cap_keeps_everything():
    store = BoundedSessionStore(cap=8)
    d = _mkdirs(3)
    for sid, path in enumerate(d):
        store[sid] = path
    assert set(store) == {0, 1, 2}
    assert all(os.path.isdir(p) for p in d)


def test_eviction_survives_missing_dir():
    store = BoundedSessionStore(cap=1)
    store[0] = os.path.join(tempfile.gettempdir(), "bss_never_created_xyz")
    store[1] = _mkdirs(1)[0]                    # evicting sid 0 must not raise
    assert set(store) == {1}
