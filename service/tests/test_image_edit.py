"""Mask-guided image-edit application service, client, and HTTP adapter."""
from __future__ import annotations

import base64
import io

import numpy as np
import pytest
from fastapi.testclient import TestClient
from PIL import Image

from service.app import app
from service.core.config import ConfigurationError, ImageEditSettings
from service.core.errors import (
    ImageEditUnavailable,
    InvalidImageEdit,
    UnknownImageEditModel,
)
from service.image_edit.http_dependencies import ImageEditHttpRuntime
from service.image_edit.ingest import load_mask_upload
from service.image_edit.service import ImageEditResult, edit_image
from service.infrastructure import image_edit_client
from service.media.ingest import load_image_upload


def _png(array: np.ndarray) -> bytes:
    buffer = io.BytesIO()
    Image.fromarray(array).save(buffer, format="PNG")
    return buffer.getvalue()


def _png_b64(array: np.ndarray) -> str:
    return base64.b64encode(_png(array)).decode("ascii")


def _sample():
    source = np.zeros((8, 8, 3), np.uint8)
    source[:, :, 1] = 17
    mask = np.zeros((8, 8, 3), np.uint8)
    mask[2:6, 3:7] = 255
    return source, mask


def test_edit_image_preserves_pixels_outside_mask_and_passes_contract():
    source, mask = _sample()
    seen = {}

    def editor(image, worker_mask, model, seed):
        seen.update(
            image=image,
            mask=worker_mask,
            model=model,
            seed=seed,
        )
        return np.full_like(image, 220)

    result = edit_image(
        source,
        mask,
        model="diffueraser",
        seed=42,
        editor_fn=editor,
    )
    selected = mask[:, :, 0] > 0
    assert np.array_equal(result.image[~selected], source[~selected])
    assert np.all(result.image[selected] == 220)
    assert set(np.unique(seen["mask"])) == {0, 255}
    assert seen["model"] == "diffueraser"
    assert seen["seed"] == 42
    assert result.mask_fraction == pytest.approx(16 / 64)


@pytest.mark.parametrize(
    ("mask", "error"),
    [
        (np.zeros((8, 8, 3), np.uint8), "mask is empty"),
        (np.ones((7, 8, 3), np.uint8), "dimensions must match"),
    ],
)
def test_edit_image_rejects_invalid_masks(mask, error):
    source, _ = _sample()
    with pytest.raises(InvalidImageEdit, match=error):
        edit_image(
            source,
            mask,
            model="diffueraser",
            seed=1,
            editor_fn=lambda *args: source,
        )


def test_edit_image_rejects_unknown_model_and_bad_worker_shape():
    source, mask = _sample()
    with pytest.raises(UnknownImageEditModel):
        edit_image(
            source,
            mask,
            model="not-a-model",
            seed=1,
            editor_fn=lambda *args: source,
        )
    with pytest.raises(InvalidImageEdit, match="dimensions"):
        edit_image(
            source,
            mask,
            model="diffueraser",
            seed=1,
            editor_fn=lambda *args: np.zeros((2, 2, 3), np.uint8),
        )


def test_worker_client_png_round_trip(monkeypatch):
    source, mask = _sample()
    edited = np.full_like(source, 99)
    seen = {}

    def fake_post(url, payload, timeout):
        seen.update(url=url, payload=payload, timeout=timeout)
        return {
            "model": "diffueraser",
            "image": _png_b64(edited),
        }

    monkeypatch.setattr(image_edit_client, "_post_json", fake_post)
    editor = image_edit_client.make_worker_editor("http://box:8002/", 12.5)
    output = editor(source, mask[:, :, 0], "diffueraser", 7)
    assert np.array_equal(output, edited)
    assert seen["url"] == "http://box:8002/edit"
    assert seen["timeout"] == 12.5
    assert set(seen["payload"]) == {"model", "image", "mask", "seed"}
    assert seen["payload"]["seed"] == 7


def test_worker_client_fail_closed_on_invalid_reply(monkeypatch):
    monkeypatch.setattr(
        image_edit_client,
        "_post_json",
        lambda *args: {"model": "diffueraser", "image": "not-base64"},
    )
    source, mask = _sample()
    editor = image_edit_client.make_worker_editor("http://box:8002", 1)
    with pytest.raises(ImageEditUnavailable):
        editor(source, mask[:, :, 0], "diffueraser", 1)


class _Lease:
    def __init__(self):
        self.released = False

    def release(self):
        self.released = True


class _Admission:
    def __init__(self, lease):
        self.lease = lease

    def acquire(self):
        return self.lease


def test_image_edit_route_returns_png_and_releases_gpu_lease(monkeypatch):
    source, mask = _sample()
    lease = _Lease()

    def fake_edit(image, painted_mask, *, model, seed):
        assert image.shape == source.shape
        assert painted_mask.shape == mask.shape[:2]
        assert model == "diffueraser"
        assert seed == 123
        return ImageEditResult(
            image=np.full_like(source, 31),
            model="diffueraser",
            seed=seed,
            mask_fraction=0.25,
        )

    runtime = ImageEditHttpRuntime(
        load_image=load_image_upload,
        load_mask=load_mask_upload,
        edit_image=fake_edit,
        admission_for=lambda name: _Admission(lease),
    )
    monkeypatch.setattr(app.state, "image_edit_http_runtime", runtime)
    response = TestClient(app).post(
        "/tools/image-edit",
        files={
            "image": ("source.png", _png(source), "image/png"),
            "mask": ("mask.png", _png(mask), "image/png"),
        },
        data={"model": "diffueraser", "seed": "123"},
    )
    assert response.status_code == 200
    assert response.headers["content-type"] == "image/png"
    assert response.headers["x-image-edit-model"] == "diffueraser"
    assert response.headers["x-image-edit-seed"] == "123"
    with Image.open(io.BytesIO(response.content)) as output:
        assert np.all(np.asarray(output) == 31)
    assert lease.released is True


def test_image_edit_route_maps_worker_failure_to_503(monkeypatch):
    source, mask = _sample()

    def unavailable(*args, **kwargs):
        raise ImageEditUnavailable("worker unavailable")

    runtime = ImageEditHttpRuntime(
        load_image=load_image_upload,
        load_mask=load_mask_upload,
        edit_image=unavailable,
        admission_for=lambda name: _Admission(_Lease()),
    )
    monkeypatch.setattr(app.state, "image_edit_http_runtime", runtime)
    response = TestClient(app).post(
        "/tools/image-edit",
        files={
            "image": ("source.png", _png(source), "image/png"),
            "mask": ("mask.png", _png(mask), "image/png"),
        },
    )
    assert response.status_code == 503
    assert response.json() == {"detail": "worker unavailable"}


def test_image_edit_settings_defaults_and_url_validation(monkeypatch):
    monkeypatch.delenv("COPILOT_IMAGE_EDIT_WORKER_URL", raising=False)
    monkeypatch.delenv("COPILOT_IMAGE_EDIT_TIMEOUT", raising=False)
    monkeypatch.delenv("COPILOT_IMAGE_EDIT_MODEL", raising=False)
    settings = ImageEditSettings.from_env()
    assert settings.worker_url == "http://127.0.0.1:8002"
    assert settings.timeout_seconds == 1200.0
    assert settings.default_model == "diffueraser"

    monkeypatch.setenv("COPILOT_IMAGE_EDIT_WORKER_URL", "not-a-url")
    with pytest.raises(ConfigurationError):
        ImageEditSettings.from_env()


def test_transparent_mask_upload_uses_alpha_channel():
    rgba = np.zeros((8, 8, 4), np.uint8)
    rgba[2:6, 3:7, :3] = [255, 0, 0]
    rgba[2:6, 3:7, 3] = 255
    buffer = io.BytesIO()
    Image.fromarray(rgba, mode="RGBA").save(buffer, format="PNG")

    from starlette.datastructures import Headers, UploadFile

    upload = UploadFile(
        file=io.BytesIO(buffer.getvalue()),
        filename="paint.png",
        headers=Headers({"content-type": "image/png"}),
    )
    mask = load_mask_upload(upload)
    assert mask.shape == (8, 8)
    assert np.all(mask[2:6, 3:7] == 255)
    assert not np.any(mask[:2])
