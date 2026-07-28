"""Box worker tests without loading the external GPU model."""
from __future__ import annotations

import base64
import io

import numpy as np
from fastapi.testclient import TestClient
from PIL import Image

from scripts import image_edit_worker


def _b64(array: np.ndarray) -> str:
    buffer = io.BytesIO()
    Image.fromarray(array).save(buffer, format="PNG")
    return base64.b64encode(buffer.getvalue()).decode("ascii")


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


def test_worker_health_does_not_load_model(monkeypatch):
    monkeypatch.setattr(
        image_edit_worker.DiffuEraserRunner,
        "available",
        classmethod(lambda cls: True),
    )
    response = TestClient(image_edit_worker.app).get("/health")
    assert response.status_code == 200
    assert response.json()["models"] == ["diffueraser"]
