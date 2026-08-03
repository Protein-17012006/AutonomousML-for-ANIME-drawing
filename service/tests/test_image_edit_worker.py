"""Box worker tests without loading the external GPU model."""
from __future__ import annotations

import base64
import io
from pathlib import Path

import numpy as np
import pytest
from fastapi.testclient import TestClient
from PIL import Image

from scripts import image_edit_worker


def _b64(array: np.ndarray) -> str:
    buffer = io.BytesIO()
    Image.fromarray(array).save(buffer, format="PNG")
    return base64.b64encode(buffer.getvalue()).decode("ascii")


def _png_b64_rgb(width: int, height: int, value: int = 0) -> str:
    return _b64(np.full((height, width, 3), value, np.uint8))


def _png_b64_mask(width: int, height: int) -> str:
    data = np.zeros((height, width), np.uint8)
    data[2:5, 2:5] = 255
    return _b64(data)


def test_worker_edit_contract_without_gpu(monkeypatch):
    source = np.zeros((8, 8, 3), np.uint8)
    mask = np.zeros((8, 8), np.uint8)
    mask[2:6, 2:6] = 255
    edited = np.full_like(source, 77)
    seen = {}

    def fake_run(image, worker_mask, *, seed):
        seen.update(image=image, mask=worker_mask, seed=seed)
        return edited

    monkeypatch.setattr(image_edit_worker._runner, "run", fake_run)
    response = TestClient(image_edit_worker.app).post(
        "/edit",
        json={
            "model": "diffueraser",
            "image": _b64(source),
            "mask": _b64(mask),
            "seed": 9,
        },
    )
    assert response.status_code == 200
    body = response.json()
    assert body["model"] == "diffueraser"
    output = image_edit_worker._decode_png(body["image"], grayscale=False)
    assert np.array_equal(output, edited)
    assert seen["seed"] == 9
    assert seen["mask"].shape == mask.shape


def test_worker_rejects_unknown_model_and_bad_png():
    client = TestClient(image_edit_worker.app)
    source = np.zeros((8, 8, 3), np.uint8)
    mask = np.ones((8, 8), np.uint8) * 255
    response = client.post(
        "/edit",
        json={
            "model": "unknown",
            "image": _b64(source),
            "mask": _b64(mask),
            "seed": 1,
        },
    )
    assert response.status_code == 422

    response = client.post(
        "/edit",
        json={
            "model": "diffueraser",
            "image": "not-base64",
            "mask": _b64(mask),
            "seed": 1,
        },
    )
    assert response.status_code == 422


def _span_payload(**overrides) -> dict:
    payload = {
        "model": "diffueraser",
        "frames": [_png_b64_rgb(8, 8)] * 4,
        "masks": {"1": _png_b64_mask(8, 8)},
        "seed": 2026,
        "refinement_passes": 1,
    }
    payload.update(overrides)
    return payload


def test_edit_span_hands_the_runner_every_distinct_frame(monkeypatch):
    # The point of this route. The still path pads ONE frame to 22 copies, so a
    # test that only counts frames stays green on the very degradation this
    # endpoint exists to fix: assert the frames arrive DISTINCT and in order.
    monkeypatch.setattr(
        image_edit_worker.DiffuEraserRunner,
        "available",
        classmethod(lambda cls: True),
    )
    seen = {}

    def fake_run_span(frames, masks, *, seed, refinement_passes):
        seen.update(
            frames=frames, masks=masks, seed=seed, passes=refinement_passes
        )
        return [frame.copy() for frame in frames]

    monkeypatch.setattr(
        image_edit_worker._runner, "run_span", fake_run_span, raising=False
    )
    response = TestClient(image_edit_worker.app).post(
        "/edit-span",
        json=_span_payload(
            frames=[_png_b64_rgb(8, 8, value=index) for index in range(24)],
            masks={"12": _png_b64_mask(8, 8)},
            seed=9,
            refinement_passes=3,
        ),
    )
    assert response.status_code == 200
    assert len(response.json()["frames"]) == 24
    assert [int(frame[0, 0, 0]) for frame in seen["frames"]] == list(range(24))
    assert sorted(seen["masks"]) == [12]
    assert seen["seed"] == 9 and seen["passes"] == 3


def test_edit_span_refuses_a_mask_index_outside_the_span():
    response = TestClient(image_edit_worker.app).post(
        "/edit-span", json=_span_payload(masks={"9": _png_b64_mask(8, 8)})
    )
    assert response.status_code == 422


def test_edit_span_refuses_a_mask_index_one_past_the_last_frame():
    # The boundary, not a wild index: a span of 4 frames has no frame 4. Without
    # this, weakening the guard from `>=` to `>` stays green.
    response = TestClient(image_edit_worker.app).post(
        "/edit-span", json=_span_payload(masks={"4": _png_b64_mask(8, 8)})
    )
    assert response.status_code == 422


def test_edit_span_refuses_a_mask_key_that_is_not_an_integer():
    response = TestClient(image_edit_worker.app).post(
        "/edit-span", json=_span_payload(masks={"middle": _png_b64_mask(8, 8)})
    )
    assert response.status_code == 422


def test_edit_span_refuses_an_empty_mask_set():
    response = TestClient(image_edit_worker.app).post(
        "/edit-span", json=_span_payload(masks={})
    )
    assert response.status_code == 422


def test_edit_span_refuses_an_empty_span():
    response = TestClient(image_edit_worker.app).post(
        "/edit-span", json=_span_payload(frames=[], masks={"0": _png_b64_mask(8, 8)})
    )
    assert response.status_code == 422


def test_edit_span_refuses_more_frames_than_the_cap():
    # 481 frames, one over MAX_SPAN_FRAMES. Pinned as a literal: an expectation
    # written as MAX_SPAN_FRAMES + 1 moves with the constant and pins nothing.
    # The frames must be 8x8 so they MATCH the mask -- at 2x2 this returns 422
    # for a shape mismatch and the cap is never reached.
    response = TestClient(image_edit_worker.app).post(
        "/edit-span",
        json=_span_payload(frames=[_png_b64_rgb(8, 8)] * 481),
    )
    assert response.status_code == 422
    assert "out of range" in response.json()["detail"]


def test_edit_span_refuses_refinement_passes_above_the_cap():
    response = TestClient(image_edit_worker.app).post(
        "/edit-span", json=_span_payload(refinement_passes=21)
    )
    assert response.status_code == 422


def test_edit_span_refuses_an_unknown_model():
    response = TestClient(image_edit_worker.app).post(
        "/edit-span", json=_span_payload(model="unknown")
    )
    assert response.status_code == 422


def test_edit_span_reports_the_worker_unavailable_rather_than_failing_open():
    monkeypatch_value = image_edit_worker.DiffuEraserRunner.available
    try:
        image_edit_worker.DiffuEraserRunner.available = classmethod(
            lambda cls: False
        )
        response = TestClient(image_edit_worker.app).post(
            "/edit-span", json=_span_payload()
        )
        assert response.status_code == 503
    finally:
        image_edit_worker.DiffuEraserRunner.available = monkeypatch_value


def test_run_span_refuses_a_mask_that_does_not_match_the_frame(monkeypatch):
    # run() already refuses a mask whose shape differs from the image; without
    # the same refusal here the mask video would be encoded at a different size
    # than the input video and the model would be asked to align two grids.
    monkeypatch.setattr(
        image_edit_worker.DiffuEraserRunner,
        "available",
        classmethod(lambda cls: True),
    )
    frames = [np.zeros((8, 8, 3), np.uint8) for _ in range(4)]
    with pytest.raises(ValueError, match="mask"):
        image_edit_worker._runner.run_span(
            frames,
            {1: np.full((16, 16), 255, np.uint8)},
            seed=1,
            refinement_passes=1,
        )


def test_run_span_treats_a_mask_below_the_threshold_as_empty(monkeypatch):
    # The threshold is > 8, matching run() and span.decode_mask. A mask of 5 is
    # compression noise, not a stroke; every other test paints 255, so without
    # this the constant could be anything.
    monkeypatch.setattr(
        image_edit_worker.DiffuEraserRunner,
        "available",
        classmethod(lambda cls: True),
    )
    frames = [np.zeros((8, 8, 3), np.uint8) for _ in range(4)]
    with pytest.raises(ValueError, match="empty"):
        image_edit_worker._runner.run_span(
            frames,
            {1: np.full((8, 8), 5, np.uint8)},
            seed=1,
            refinement_passes=1,
        )


def test_run_span_refuses_frames_of_differing_sizes(monkeypatch):
    monkeypatch.setattr(
        image_edit_worker.DiffuEraserRunner,
        "available",
        classmethod(lambda cls: True),
    )
    frames = [np.zeros((8, 8, 3), np.uint8), np.zeros((9, 8, 3), np.uint8)]
    with pytest.raises(ValueError, match="size"):
        image_edit_worker._runner.run_span(
            frames,
            {0: np.full((8, 8), 255, np.uint8)},
            seed=1,
            refinement_passes=1,
        )


def _fake_subprocess_seams(monkeypatch, captured: dict):
    """Stand in for ffmpeg and the DiffuEraser venv.

    Records what run_span actually WROTE to disk, then fabricates the outputs
    the real commands would have produced, so the body of run_span runs end to
    end without a GPU.
    """
    monkeypatch.setattr(
        image_edit_worker.DiffuEraserRunner,
        "available",
        classmethod(lambda cls: True),
    )

    def fake_encode(self, frames_dir, output_path, *, timeout):
        written = sorted(frames_dir.glob("*.png"))
        captured.setdefault(frames_dir.name, []).extend(
            np.array(Image.open(path).convert("L"), dtype=np.uint8)
            for path in written
        )
        output_path.write_bytes(b"fake-video")

    def fake_run(command, *, cwd, timeout):
        if any("run_diffueraser.py" in part for part in command):
            save_path = Path(command[command.index("--save_path") + 1])
            (save_path / "diffueraser_result.mp4").write_bytes(b"fake-result")
            return
        pattern = Path(command[-1])
        count = len(captured["frames"])
        for index in range(1, count + 1):
            Image.fromarray(np.full((8, 8, 3), 200, np.uint8)).save(
                pattern.parent / f"{index:04d}.png"
            )

    monkeypatch.setattr(
        image_edit_worker.DiffuEraserRunner, "_encode_sequence", fake_encode
    )
    monkeypatch.setattr(
        image_edit_worker.DiffuEraserRunner, "_run", staticmethod(fake_run)
    )


def test_run_span_gives_unpainted_frames_an_all_black_mask(monkeypatch):
    # The load-bearing semantic of the span: only the painted frames carry ink,
    # every neighbour is handed to the model as context it must preserve. If the
    # painted mask leaked onto the neighbours the model would erase the cut.
    captured: dict = {}
    _fake_subprocess_seams(monkeypatch, captured)
    frames = [np.full((8, 8, 3), index, np.uint8) for index in range(6)]
    painted = np.zeros((8, 8), np.uint8)
    painted[2:5, 2:5] = 255

    output = image_edit_worker._runner.run_span(
        frames, {3: painted}, seed=1, refinement_passes=1
    )

    assert len(output) == 6
    masks = captured["masks"]
    assert len(masks) == 6
    assert masks[3].max() == 255
    assert all(masks[index].max() == 0 for index in (0, 1, 2, 4, 5))


def test_run_span_writes_the_real_frames_in_order(monkeypatch):
    # run() pads ONE still to CONTEXT_FRAMES copies; this asserts the span path
    # writes six DISTINCT frames, which is the degradation being repaired.
    captured: dict = {}
    _fake_subprocess_seams(monkeypatch, captured)
    frames = [np.full((8, 8, 3), index * 10, np.uint8) for index in range(6)]

    image_edit_worker._runner.run_span(
        frames, {3: np.full((8, 8), 255, np.uint8)}, seed=1, refinement_passes=1
    )

    assert [int(frame[0, 0]) for frame in captured["frames"]] == [
        0, 10, 20, 30, 40, 50
    ]


def test_run_span_passes_the_span_length_and_refinement_passes_through(monkeypatch):
    captured: dict = {}
    _fake_subprocess_seams(monkeypatch, captured)
    commands: list[list[str]] = []
    original = image_edit_worker.DiffuEraserRunner._run

    def recording(command, *, cwd, timeout):
        commands.append(list(command))
        return original(command, cwd=cwd, timeout=timeout)

    monkeypatch.setattr(
        image_edit_worker.DiffuEraserRunner, "_run", staticmethod(recording)
    )
    frames = [np.zeros((8, 8, 3), np.uint8) for _ in range(6)]

    image_edit_worker._runner.run_span(
        frames, {3: np.full((8, 8), 255, np.uint8)}, seed=7, refinement_passes=4
    )

    inference = next(
        c for c in commands if any("run_diffueraser.py" in p for p in c)
    )
    assert inference[inference.index("--nframes") + 1] == "6"
    assert inference[inference.index("--refinement_passes") + 1] == "4"
    assert inference[inference.index("--seed") + 1] == "7"
    # 6 frames at CONTEXT_FPS 4 is 1.5 seconds, not the still path's 5.5.
    assert inference[inference.index("--video_length") + 1] == "1.500"


def test_run_span_refuses_a_short_result(monkeypatch):
    # A span that comes back with fewer frames than it went in with is a partial
    # repair; half a repaired span written into a session is the one outcome
    # this feature must never produce.
    captured: dict = {}
    _fake_subprocess_seams(monkeypatch, captured)

    def truncating(command, *, cwd, timeout):
        if any("run_diffueraser.py" in part for part in command):
            save_path = Path(command[command.index("--save_path") + 1])
            (save_path / "diffueraser_result.mp4").write_bytes(b"fake-result")
            return
        pattern = Path(command[-1])
        for index in range(1, 4):
            Image.fromarray(np.zeros((8, 8, 3), np.uint8)).save(
                pattern.parent / f"{index:04d}.png"
            )

    monkeypatch.setattr(
        image_edit_worker.DiffuEraserRunner, "_run", staticmethod(truncating)
    )
    frames = [np.zeros((8, 8, 3), np.uint8) for _ in range(6)]
    with pytest.raises(RuntimeError, match="did not return frame"):
        image_edit_worker._runner.run_span(
            frames, {3: np.full((8, 8), 255, np.uint8)}, seed=1,
            refinement_passes=1,
        )


def test_worker_health_does_not_load_model(monkeypatch):
    monkeypatch.setattr(
        image_edit_worker.DiffuEraserRunner,
        "available",
        classmethod(lambda cls: True),
    )
    response = TestClient(image_edit_worker.app).get("/health")
    assert response.status_code == 200
    assert response.json()["models"] == ["diffueraser"]
