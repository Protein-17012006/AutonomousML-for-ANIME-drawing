"""Env-gated AWS publisher: off by default, uploads artifacts + one DDB item when on,
and NEVER raises into the session path (degrade-never-500)."""
import types

import pytest

from inbetween_copilot.pipeline.copilot import CopilotResult
from service.infrastructure import publisher


def _result():
    # Use real CopilotResult dataclass to catch field-drift bugs at test time
    pairs = [types.SimpleNamespace(index=0, action="filled"),
             types.SimpleNamespace(index=1, action="needs_key")]
    return CopilotResult(pairs=pairs, keys_requested_total=2, flagged=[1],
                         n_autopass=1, n_corrected=0, abstained=[])


class FakeS3:
    def __init__(self, fail=False):
        self.calls, self.fail = [], fail

    def upload_file(self, path, bucket, key):
        if self.fail:
            raise RuntimeError("s3 down")
        self.calls.append((path, bucket, key))


class FakeDdb:
    def __init__(self):
        self.items = []

    def put_item(self, TableName, Item):
        self.items.append((TableName, Item))


def _session_dir(tmp_path):
    (tmp_path / "montage.png").write_bytes(b"png")
    (tmp_path / "report.md").write_text("r")
    (tmp_path / "reconstructed.mp4").write_bytes(b"mp4")
    (tmp_path / "notes.txt").write_text("skip me")     # not an artifact suffix
    return tmp_path


def test_disabled_by_default(tmp_path, monkeypatch):
    monkeypatch.delenv("AWS_PUBLISH", raising=False)
    out = publisher.publish_session(1, tmp_path, _result())
    assert out == {"published": False, "pid": None, "s3_keys": [], "error": None}


def test_publishes_artifacts_and_record(tmp_path, monkeypatch):
    monkeypatch.setenv("AWS_PUBLISH", "1")
    monkeypatch.setenv("AWS_ARTIFACT_BUCKET", "b")
    monkeypatch.setenv("AWS_SESSIONS_TABLE", "t")
    s3, ddb = FakeS3(), FakeDdb()
    out = publisher.publish_session(7, _session_dir(tmp_path), _result(),
                                    clients={"s3": s3, "ddb": ddb}, pid="deadbeef")
    assert out["published"] is True and out["error"] is None
    keys = [k for _, _, k in s3.calls]
    assert keys == ["artifacts/deadbeef/montage.png",      # CloudFront /artifacts/* contract
                    "artifacts/deadbeef/reconstructed.mp4",
                    "artifacts/deadbeef/report.md"]
    (table, item), = ddb.items
    assert table == "t" and item["pid"] == {"S": "deadbeef"}
    assert item["sid"] == {"N": "7"} and item["n_pairs"] == {"N": "2"}
    assert item["flagged"] == {"S": "[1]"}
    assert item["needs_key"] == {"S": "[1]"}  # derived from pair.action == "needs_key"
    assert item["keys_requested_total"] == {"N": "2"}


def test_owned_publish_writes_owner_index_attributes(tmp_path, monkeypatch):
    monkeypatch.setenv("AWS_PUBLISH", "1")
    monkeypatch.setenv("AWS_ARTIFACT_BUCKET", "b")
    monkeypatch.setenv("AWS_SESSIONS_TABLE", "t")
    ddb = FakeDdb()
    out = publisher.publish_session(
        7,
        _session_dir(tmp_path),
        _result(),
        owner_sub="cognito-sub",
        clients={"s3": FakeS3(), "ddb": ddb},
        pid="owned-pid",
    )
    assert out["published"] is True
    (_, item), = ddb.items
    assert item["owner_sub"] == {"S": "cognito-sub"}
    timestamp = int(item["ts"]["N"])
    assert item["owner_sort"] == {
        "S": publisher.owner_sort_key(timestamp, "owned-pid")
    }


def test_s3_failure_never_raises(tmp_path, monkeypatch):
    monkeypatch.setenv("AWS_PUBLISH", "1")
    monkeypatch.setenv("AWS_ARTIFACT_BUCKET", "b")
    monkeypatch.setenv("AWS_SESSIONS_TABLE", "t")
    out = publisher.publish_session(1, _session_dir(tmp_path), _result(),
                                    clients={"s3": FakeS3(fail=True), "ddb": FakeDdb()})
    assert out["published"] is False and "s3 down" in out["error"]


def test_missing_env_never_raises(tmp_path, monkeypatch):
    monkeypatch.setenv("AWS_PUBLISH", "1")
    monkeypatch.delenv("AWS_ARTIFACT_BUCKET", raising=False)
    out = publisher.publish_session(1, _session_dir(tmp_path), _result(),
                                    clients={"s3": FakeS3(), "ddb": FakeDdb()})
    assert out["published"] is False and out["error"]


def test_app_worker_calls_publisher(tmp_path, monkeypatch):
    """POST /session must invoke publish_session once with the sid + session dir + result."""
    import service.app as appmod
    import service.composition.session_runtime as composition_mod
    from fastapi.testclient import TestClient
    from PIL import Image

    calls = []
    monkeypatch.setattr(
        composition_mod,
        "publish_session",
        lambda sid, sdir, result, *, owner_sub=None: calls.append(
            (sid, sdir, result, owner_sub)
        ),
    )
    old_runtime = appmod.app.state.session_http_runtime
    appmod.app.state.session_http_runtime = composition_mod.build_session_http_runtime()
    img = tmp_path / "k.png"
    Image.new("RGB", (64, 64), (200, 100, 50)).save(img)
    try:
        client = TestClient(appmod.app)
        with open(img, "rb") as f1, open(img, "rb") as f2:
            r = client.post("/session", files=[("keys", ("a.png", f1, "image/png")),
                                               ("keys", ("b.png", f2, "image/png"))],
                            data={"engines": "stub"})
    finally:
        appmod.app.state.session_http_runtime = old_runtime
    assert r.status_code == 200 and "event: result" in r.text
    assert len(calls) == 1
    sid, sdir, result, owner_sub = calls[0]
    assert isinstance(sid, int) and result.pairs   # real result object reached the publisher
    assert owner_sub is None
