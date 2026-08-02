"""The repair revision: one commit, or none at all.

Split deliberately. The ReviewSession tests drive the real transaction against a
real repository and a real directory, because atomicity is the load-bearing
claim and a mocked commit cannot witness it. The route tests drive refusals,
which happen before any of that.
"""
from __future__ import annotations

import base64
import io
import pathlib

import numpy as np
import pytest
from fastapi.testclient import TestClient
from PIL import Image

from service.app import app
from service.core.errors import ImageEditUnavailable, SessionNotFound
from service.image_edit.http_dependencies import ImageEditHttpRuntime
from service.review.http_dependencies import ReviewHttpRuntime
from service.review.service import ReviewSession
from service.sessions.repository import InMemorySessionRepository
from inbetween_copilot.pipeline.models import CopilotResult, PairResult
from inbetween_copilot.qa.models import FrameQA


HEIGHT = WIDTH = 32


def _mask_png() -> str:
    rgba = np.zeros((HEIGHT, WIDTH, 4), np.uint8)
    rgba[8:20, 8:20] = (255, 255, 255, 255)
    buffer = io.BytesIO()
    Image.fromarray(rgba, mode="RGBA").save(buffer, format="PNG")
    return "data:image/png;base64," + base64.b64encode(
        buffer.getvalue()).decode("ascii")


PNG = _mask_png()


def _frame(value: int) -> np.ndarray:
    return np.full((HEIGHT, WIDTH, 3), value, np.uint8)


class _Cfg:
    smoothness = 2
    cadence_fps = 12
    fps = 24
    engines = "stub"
    interpolator = "rife"
    tau_soft = 0.5
    tau_gate = 0.017


class _Eng:
    rife_engine = None
    vlm_struct_fn = None
    csq_calibrator = None
    qa_window = False
    vlm_status: dict = {}

    @staticmethod
    def qa_fn(frames):
        return False

    @staticmethod
    def softness_fn(frames):
        return 0.0


def _pair(index, action, values, *, qa_status="pass", artist_verdict=None):
    return PairResult(
        index=index, action=action,
        route="rife" if action != "needs_key" else None,
        frames=[_frame(value) for value in values] if values else None,
        qa=FrameQA(status=qa_status, reason="stub") if action != "needs_key" else None,
        keys_requested=0, artist_verdict=artist_verdict,
    )


@pytest.fixture
def live():
    """A repository holding one real session directory and one real result."""
    repository = InMemorySessionRepository()
    sid, path = repository.create()
    pairs = [
        _pair(0, "filled", (10, 20, 30), qa_status="flag", artist_verdict="reject"),
        _pair(1, "filled", (30, 40, 50), qa_status="pass", artist_verdict="accept"),
    ]
    repository.save_state(sid, {
        "result": CopilotResult(pairs=pairs, keys_requested_total=0, flagged=[0],
                                n_autopass=1),
        "cfg": _Cfg(), "eng": _Eng(), "keys": [_frame(v) for v in (10, 30, 50)],
        "rev": 3, "published_pid": "pid-1", "sampling": {}, "gt_frames": None,
    })
    (pathlib.Path(path) / "reconstructed.mp4").write_bytes(b"old")
    return repository, sid, path


class _Rendered:
    explanations: dict = {}
    annotated_files: dict = {}
    pair_files: dict = {}
    key_files: dict = {}
    frame_count = 5
    duration = 0.2
    compare_file = None


def _render(result, keys, out_dir, **kwargs):
    (pathlib.Path(out_dir) / "reconstructed.mp4").write_bytes(b"new")
    return _Rendered()


def _review(repository, render=_render) -> ReviewSession:
    return ReviewSession(repository, render)


def _bright_editor(frames, masks, *, model, seed, refinement_passes):
    return [np.full_like(frame, 200) for frame in frames]


# --- the transaction -------------------------------------------------------

def test_repair_commits_frames_and_the_new_verdict_in_one_revision(live):
    repository, sid, _path = live
    outcome = _review(repository).repair_pair(
        sid, 0, [{"frame": 1, "png": PNG}], span_editor=_bright_editor)

    stored = repository.state_for(sid)
    assert stored["rev"] == 4
    repaired = stored["result"].pairs[0]
    assert not np.array_equal(repaired.frames[1], _frame(20))
    assert outcome.result.pairs[0].frames[1] is repaired.frames[1]


def test_repair_installs_the_re_run_verdict_over_the_old_one(live):
    # The load-bearing rule. Counting qa_fn calls is not enough: a repair that
    # recomputes the verdict and then never stores it leaves the session holding
    # NEW PIXELS UNDER AN OLD VERDICT, which is the exact defect this forbids.
    repository, sid, _path = live
    assert repository.state_for(sid)["result"].pairs[1].qa.status == "pass"
    repository.state_for(sid)["eng"].qa_fn = staticmethod(lambda frames: True)
    try:
        _review(repository).repair_pair(
            sid, 1, [{"frame": 3, "png": PNG}], span_editor=_bright_editor)
    finally:
        repository.state_for(sid)["eng"].qa_fn = _Eng.qa_fn
    stored = repository.state_for(sid)["result"]
    assert stored.pairs[1].qa.status == "flag"
    assert stored.pairs[1].qa.reason == "detector"
    # and the aggregate the UI reads was rebuilt from it
    assert 1 in stored.flagged


def test_repair_clears_artist_verdict_for_the_repaired_pair_only(live):
    repository, sid, _path = live
    _review(repository).repair_pair(
        sid, 0, [{"frame": 1, "png": PNG}], span_editor=_bright_editor)

    pairs = repository.state_for(sid)["result"].pairs
    assert pairs[0].artist_verdict is None
    assert pairs[1].artist_verdict == "accept"


def test_repair_leaves_the_session_byte_identical_when_the_worker_is_down(live):
    repository, sid, path = live
    before = repository.state_for(sid)
    before_frames = [np.asarray(f).tobytes() for f in before["result"].pairs[0].frames]

    def down(*args, **kwargs):
        raise ImageEditUnavailable("worker down")

    with pytest.raises(ImageEditUnavailable):
        _review(repository).repair_pair(
            sid, 0, [{"frame": 1, "png": PNG}], span_editor=down)

    after = repository.state_for(sid)
    assert after["rev"] == 3
    assert [np.asarray(f).tobytes() for f in after["result"].pairs[0].frames] == before_frames
    assert after["result"].pairs[0].artist_verdict == "reject"
    assert (pathlib.Path(path) / "reconstructed.mp4").read_bytes() == b"old"


def test_repair_publishes_nothing_when_the_render_fails(live):
    # The artifact generation and the state must move together. A render that
    # dies after the pixels are computed must not leave a bumped revision.
    repository, sid, path = live

    def exploding_render(*args, **kwargs):
        raise RuntimeError("render failed")

    before = [np.asarray(f).tobytes()
              for f in repository.state_for(sid)["result"].pairs[0].frames]
    with pytest.raises(RuntimeError):
        _review(repository, exploding_render).repair_pair(
            sid, 0, [{"frame": 1, "png": PNG}], span_editor=_bright_editor)

    stored = repository.state_for(sid)
    assert stored["rev"] == 3
    assert (pathlib.Path(path) / "reconstructed.mp4").read_bytes() == b"old"
    # The revision number alone is not enough: an early state write would leave
    # repaired pixels behind an unbumped rev, with no artifacts to match them.
    assert [np.asarray(f).tobytes() for f in stored["result"].pairs[0].frames] == before
    assert stored["result"].pairs[0].artist_verdict == "reject"


def test_repair_refuses_a_needs_key_pair_before_touching_the_gpu(live):
    repository, sid, _path = live
    state = repository.state_for(sid)
    state["result"].pairs[1].action = "needs_key"
    state["result"].pairs[1].frames = None

    def must_not_run(*args, **kwargs):
        raise AssertionError("the GPU was reached for a pair with no frame")

    with pytest.raises(ValueError, match="no generated frame"):
        _review(repository).repair_pair(
            sid, 1, [{"frame": 3, "png": PNG}], span_editor=must_not_run)


def test_repair_recomputes_neighbours_when_qa_judges_a_shared_window(live):
    # With qa_window on, production QA judges a 16-frame window spanning the run,
    # so pair 1's verdict was computed from pixels pair 0 has just changed.
    repository, sid, _path = live
    state = repository.state_for(sid)
    state["eng"].qa_window = True
    seen = []

    def counting_qa(frames):
        seen.append(len(frames))
        return False

    state["eng"].qa_fn = counting_qa
    try:
        _review(repository).repair_pair(
            sid, 0, [{"frame": 1, "png": PNG}], span_editor=_bright_editor)
    finally:
        state["eng"].qa_window = False
        state["eng"].qa_fn = _Eng.qa_fn
    assert len(seen) == 2          # both pairs in the contiguous run
    assert set(seen) == {16}       # the calibrated window width, not a triplet


def test_repair_recomputes_only_the_repaired_pair_without_shared_windows(live):
    repository, sid, _path = live
    seen = []

    def counting_qa(frames):
        seen.append(len(frames))
        return False

    repository.state_for(sid)["eng"].qa_fn = counting_qa
    try:
        _review(repository).repair_pair(
            sid, 0, [{"frame": 1, "png": PNG}], span_editor=_bright_editor)
    finally:
        repository.state_for(sid)["eng"].qa_fn = _Eng.qa_fn
    assert seen == [3]             # the pair's own triplet


# --- the route -------------------------------------------------------------

def _install(monkeypatch, repository, review, *, span_editor=_bright_editor,
             publish=None):
    from service.image_edit.session_repair import validate_repair_request

    monkeypatch.setattr(app.state, "image_edit_http_runtime", ImageEditHttpRuntime(
        load_image=None, load_mask=None, edit_image=None,
        admission_for=lambda name: _Admission(), span_editor=span_editor,
        validate_repair=validate_repair_request))
    monkeypatch.setattr(app.state, "review_http_runtime", ReviewHttpRuntime(
        review_for=lambda sessions: review, load_image=None,
        admission_for=lambda name: _Admission(),
        publish_review=publish or (lambda *a, **k: {"published": True})))
    monkeypatch.setattr(
        "service.sessions.dependencies.default_session_repository", repository,
        raising=False)
    app.dependency_overrides[
        __import__("service.sessions.http_dependencies", fromlist=["x"])
        .get_session_repository] = lambda: repository


class _Lease:
    def release(self):
        pass


class _Admission:
    def acquire(self):
        return _Lease()


@pytest.fixture(autouse=True)
def _clear_overrides():
    yield
    app.dependency_overrides.clear()


def test_route_refuses_a_repair_when_no_span_worker_is_configured(monkeypatch, live):
    repository, sid, _path = live
    _install(monkeypatch, repository, _review(repository), span_editor=None)
    response = TestClient(app).post(
        f"/session/{sid}/pair/0/repair",
        json={"masks": [{"frame": 1, "png": PNG}], "refinement_passes": 1})
    assert response.status_code == 503


def test_route_404s_an_unknown_session(monkeypatch, live):
    repository, _sid, _path = live

    class _Missing:
        def state(self, sid):
            raise SessionNotFound("gone")

    _install(monkeypatch, repository, _Missing())
    response = TestClient(app).post(
        "/session/999/pair/0/repair",
        json={"masks": [{"frame": 1, "png": PNG}], "refinement_passes": 1})
    assert response.status_code == 404


def test_route_422s_and_names_the_rule_that_fired(monkeypatch, live):
    repository, sid, _path = live
    _install(monkeypatch, repository, _review(repository))
    response = TestClient(app).post(
        f"/session/{sid}/pair/0/repair",
        json={"masks": [{"frame": 1, "png": PNG}], "refinement_passes": 99})
    assert response.status_code == 422
    assert "refinement" in response.json()["detail"]


def test_route_409s_while_another_revision_runs_for_that_session(monkeypatch, live):
    # The reservation is shared with review on purpose: a repair must not run
    # beside a re-run or a verdict batch on the same session.
    from service.review.api import _release_review_job, _reserve_review_job

    repository, sid, _path = live
    _install(monkeypatch, repository, _review(repository))
    _reserve_review_job(sid, repository)
    try:
        response = TestClient(app).post(
            f"/session/{sid}/pair/0/repair",
            json={"masks": [{"frame": 1, "png": PNG}], "refinement_passes": 1})
        assert response.status_code == 409
    finally:
        _release_review_job(sid, repository)


def test_route_409s_a_session_that_has_not_been_published_yet(monkeypatch, live):
    repository, sid, _path = live
    state = repository.state_for(sid)
    state["published_pid"] = None
    _install(monkeypatch, repository, _review(repository))
    response = TestClient(app).post(
        f"/session/{sid}/pair/0/repair",
        json={"masks": [{"frame": 1, "png": PNG}], "refinement_passes": 1})
    assert response.status_code == 409


def test_route_streams_the_repaired_pair_and_result(monkeypatch, live):
    repository, sid, _path = live
    _install(monkeypatch, repository, _review(repository))
    response = TestClient(app).post(
        f"/session/{sid}/pair/0/repair",
        json={"masks": [{"frame": 1, "png": PNG}], "refinement_passes": 1})
    assert response.status_code == 200
    assert "event: pair" in response.text
    assert "event: result" in response.text
    assert repository.state_for(sid)["rev"] == 4


def test_route_reports_a_failed_durable_publish_and_does_not_claim_success(
    monkeypatch, live,
):
    repository, sid, _path = live
    _install(monkeypatch, repository, _review(repository),
             publish=lambda *a, **k: {"published": False, "error": "s3 down"})
    response = TestClient(app).post(
        f"/session/{sid}/pair/0/repair",
        json={"masks": [{"frame": 1, "png": PNG}], "refinement_passes": 1})
    assert "event: error" in response.text
    assert "s3 down" in response.text
