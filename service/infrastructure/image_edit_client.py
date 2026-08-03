"""HTTP adapter for the box-local image-edit worker."""
from __future__ import annotations

import base64
import io
import json
import urllib.error
import urllib.request

import numpy as np
from PIL import Image, UnidentifiedImageError

from service.core.errors import ImageEditUnavailable


def _png_b64(array: np.ndarray, *, grayscale: bool = False) -> str:
    buffer = io.BytesIO()
    image = Image.fromarray(array, mode="L" if grayscale else "RGB")
    image.save(buffer, format="PNG")
    return base64.b64encode(buffer.getvalue()).decode("ascii")


def _decode_png(payload: str) -> np.ndarray:
    try:
        raw = base64.b64decode(payload, validate=True)
        with Image.open(io.BytesIO(raw)) as image:
            image.load()
            return np.array(image.convert("RGB"), dtype=np.uint8, copy=True)
    except (ValueError, TypeError, UnidentifiedImageError, OSError) as exc:
        raise ImageEditUnavailable(
            "image-edit worker returned an invalid PNG"
        ) from exc


def _post_json(url: str, payload: dict, timeout: float) -> dict:
    request = urllib.request.Request(
        url,
        data=json.dumps(payload, separators=(",", ":")).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


def make_worker_editor(base_url: str, timeout_seconds: float):
    """Return editor_fn(image, mask, model, seed) for the application service."""
    endpoint = base_url.rstrip("/") + "/edit"

    def edit(image, mask, model: str, seed: int) -> np.ndarray:
        payload = {
            "model": model,
            "image": _png_b64(np.asarray(image, dtype=np.uint8)),
            "mask": _png_b64(np.asarray(mask, dtype=np.uint8), grayscale=True),
            "seed": seed,
        }
        try:
            response = _post_json(endpoint, payload, timeout_seconds)
            if not isinstance(response, dict) or not isinstance(
                response.get("image"), str
            ):
                raise ValueError("missing image")
            if response.get("model") != model:
                raise ValueError("model mismatch")
            return _decode_png(response["image"])
        except ImageEditUnavailable:
            raise
        except urllib.error.HTTPError as exc:
            raise ImageEditUnavailable(
                f"image-edit worker rejected the request (HTTP {exc.code})"
            ) from exc
        except (OSError, TimeoutError, ValueError, TypeError, json.JSONDecodeError) as exc:
            raise ImageEditUnavailable(
                "image-edit worker is unavailable or returned invalid data"
            ) from exc

    return edit


def make_worker_span_editor(base_url: str, timeout_seconds: float):
    """Return span_edit(frames, masks, model, seed, refinement_passes).

    A span that does not come back whole is reported as the worker being
    unavailable rather than as a partial result: half a repaired span written
    into a session is the one outcome this feature must never produce. The
    mismatch carries its own message so it is diagnosable apart from a dead
    socket, which raises the same class.
    """
    endpoint = base_url.rstrip("/") + "/edit-span"

    def span_edit(
        frames,
        masks,
        *,
        model: str,
        seed: int,
        refinement_passes: int,
    ) -> list[np.ndarray]:
        payload = {
            "model": model,
            "frames": [
                _png_b64(np.asarray(frame, dtype=np.uint8)) for frame in frames
            ],
            "masks": {
                str(index): _png_b64(
                    np.asarray(mask, dtype=np.uint8), grayscale=True
                )
                for index, mask in masks.items()
            },
            "seed": seed,
            "refinement_passes": refinement_passes,
        }
        try:
            response = _post_json(endpoint, payload, timeout_seconds)
            if not isinstance(response, dict):
                raise ValueError("malformed reply")
            if response.get("model") != model:
                raise ImageEditUnavailable(
                    "image-edit worker answered with model "
                    f"{response.get('model')!r}, not {model!r}"
                )
            returned = response.get("frames")
            if not isinstance(returned, list) or len(returned) != len(payload["frames"]):
                count = len(returned) if isinstance(returned, list) else 0
                raise ImageEditUnavailable(
                    f"image-edit worker returned {count} frames for a span of "
                    f"{len(payload['frames'])}"
                )
            return [_decode_png(item) for item in returned]
        except ImageEditUnavailable:
            raise
        except urllib.error.HTTPError as exc:
            raise ImageEditUnavailable(
                f"image-edit worker rejected the span (HTTP {exc.code})"
            ) from exc
        except (OSError, TimeoutError, ValueError, TypeError, json.JSONDecodeError) as exc:
            raise ImageEditUnavailable(
                "image-edit worker is unavailable or returned invalid data"
            ) from exc

    return span_edit
