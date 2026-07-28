"""Bounded mask ingestion that preserves transparent paint overlays."""
from __future__ import annotations

import io
import warnings

import numpy as np
from fastapi import HTTPException, UploadFile
from PIL import Image, UnidentifiedImageError

from service.core.config import MediaIngestSettings
from service.media.ingest import (
    _ingest_settings,
    _read_upload_limited,
    _validate_dimensions,
)


def load_mask_upload(
    upload: UploadFile,
    *,
    settings: MediaIngestSettings | None = None,
) -> np.ndarray:
    """Decode a grayscale/RGB mask or a transparent painted overlay."""
    settings = settings or _ingest_settings()
    label = upload.filename or "mask"
    data = _read_upload_limited(
        upload,
        settings.max_image_bytes,
        label=label,
    )
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(io.BytesIO(data)) as source:
                _validate_dimensions(
                    source.width,
                    source.height,
                    label=label,
                    settings=settings,
                )
                source.load()
                bands = source.getbands()
                if "A" in bands:
                    alpha = np.array(
                        source.getchannel("A"),
                        dtype=np.uint8,
                        copy=True,
                    )
                    # A non-opaque alpha channel is the mask for transparent
                    # drawing overlays. Fully opaque RGBA masks use luminance.
                    if np.any(alpha < 255):
                        return alpha
                return np.array(
                    source.convert("L"),
                    dtype=np.uint8,
                    copy=True,
                )
    except HTTPException:
        raise
    except (
        Image.DecompressionBombError,
        Image.DecompressionBombWarning,
        UnidentifiedImageError,
        OSError,
        ValueError,
    ) as exc:
        raise HTTPException(
            status_code=422,
            detail=f"couldn't decode {label} as an image mask",
        ) from exc
