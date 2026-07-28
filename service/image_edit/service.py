"""Framework-independent mask-guided image editing."""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from service.core.errors import InvalidImageEdit, UnknownImageEditModel


SUPPORTED_MODELS = frozenset({"diffueraser"})
MAX_SEED = 2_147_483_647


@dataclass(frozen=True)
class ImageEditResult:
    image: np.ndarray
    model: str
    seed: int
    mask_fraction: float


def _rgb_image(value, *, label: str) -> np.ndarray:
    image = np.asarray(value)
    if image.ndim != 3 or image.shape[2] != 3:
        raise InvalidImageEdit(f"{label} must be an RGB image")
    if image.dtype != np.uint8:
        raise InvalidImageEdit(f"{label} must use uint8 pixels")
    return image


def _binary_mask(value, shape: tuple[int, int]) -> np.ndarray:
    mask = np.asarray(value)
    if mask.shape[:2] != shape:
        raise InvalidImageEdit(
            "image and mask dimensions must match"
        )
    if mask.ndim == 3 and mask.shape[2] in {3, 4}:
        # White-on-black masks and alpha-painted masks are both common. The
        # maximum channel preserves either representation after PNG decoding.
        mask = np.max(mask, axis=2)
    elif mask.ndim != 2:
        raise InvalidImageEdit("mask must be grayscale, RGB, or RGBA")
    selected = np.asarray(mask) > 8
    if not np.any(selected):
        raise InvalidImageEdit("mask is empty; paint at least one repair region")
    return selected


def edit_image(
    image,
    mask,
    *,
    model: str,
    seed: int,
    editor_fn,
) -> ImageEditResult:
    """Run one allowlisted editor and preserve every pixel outside the mask."""
    source = _rgb_image(image, label="image")
    normalized_model = str(model or "").strip().lower()
    if normalized_model not in SUPPORTED_MODELS:
        raise UnknownImageEditModel(
            f"unsupported image-edit model: {normalized_model or '(empty)'}"
        )
    if isinstance(seed, bool) or not isinstance(seed, int) or not 0 <= seed <= MAX_SEED:
        raise InvalidImageEdit(f"seed must be between 0 and {MAX_SEED}")

    selected = _binary_mask(mask, source.shape[:2])
    worker_mask = np.where(selected, 255, 0).astype(np.uint8)
    edited = _rgb_image(
        editor_fn(source, worker_mask, normalized_model, seed),
        label="model output",
    )
    if edited.shape != source.shape:
        raise InvalidImageEdit(
            "model output dimensions do not match the input image"
        )

    # Diffusion models can drift outside the requested region. The public tool
    # contract is stronger: outside-mask pixels are byte-identical to input.
    composited = np.array(source, copy=True)
    composited[selected] = edited[selected]
    return ImageEditResult(
        image=composited,
        model=normalized_model,
        seed=seed,
        mask_fraction=float(np.mean(selected)),
    )
