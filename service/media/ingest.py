"""Media ingestion: turn uploads (PNG keys or a dropped video) into numpy key arrays."""
from __future__ import annotations

import io
import os
import tempfile
import warnings
from typing import List

import numpy as np
from PIL import Image, UnidentifiedImageError
from fastapi import HTTPException, UploadFile

from service.core.config import MediaIngestSettings

# max key frames a decimated video may yield before we refuse the run (env-tunable).
# A finished cut at stride 2 can be thousands of keys; bound it so a dropped video
# can't pin the box for hours / exhaust memory.
_DEFAULT_INGEST = MediaIngestSettings()
# Public default aliases remain for older callers/tests that tune the private
# ingest helpers directly.  They are literals, not environment snapshots.
MAX_KEYS = _DEFAULT_INGEST.max_keys
MAX_IMAGE_BYTES = _DEFAULT_INGEST.max_image_bytes
MAX_IMAGE_TOTAL_BYTES = _DEFAULT_INGEST.max_image_total_bytes
MAX_VIDEO_BYTES = _DEFAULT_INGEST.max_video_bytes
MAX_FRAME_PIXELS = _DEFAULT_INGEST.max_frame_pixels
MAX_KEY_TOTAL_PIXELS = _DEFAULT_INGEST.max_key_total_pixels
MAX_FRAME_DIMENSION = _DEFAULT_INGEST.max_frame_dimension
MAX_VIDEO_FRAMES = _DEFAULT_INGEST.max_video_frames
# Auto-fit only coarsens the stride up to this factor of the user's stride. A clip that still
# overflows MAX_KEYS at stride*FACTOR is genuinely too long for ONE cut: rather than silently
# decimate it to a sparse, unfaithful set (gaps too large to interpolate → mostly needs-key),
# we fail loudly with the exact stride to use / advice to trim. Keeps "drop a short cut → it
# just runs" while refusing to misrepresent a long montage.
AUTOFIT_MAX_FACTOR = _DEFAULT_INGEST.autofit_max_factor


def _ingest_settings() -> MediaIngestSettings:
    """Read current env over the module's stable defaults for this operation."""
    defaults = MediaIngestSettings(
        max_keys=MAX_KEYS,
        max_image_bytes=MAX_IMAGE_BYTES,
        max_image_total_bytes=MAX_IMAGE_TOTAL_BYTES,
        max_video_bytes=MAX_VIDEO_BYTES,
        max_frame_pixels=MAX_FRAME_PIXELS,
        max_key_total_pixels=MAX_KEY_TOTAL_PIXELS,
        max_frame_dimension=MAX_FRAME_DIMENSION,
        max_video_frames=MAX_VIDEO_FRAMES,
        autofit_max_factor=AUTOFIT_MAX_FACTOR,
    )
    return MediaIngestSettings.from_env(defaults)


def _read_upload_limited(upload: UploadFile, limit: int, *, label: str) -> bytes:
    """Read at most ``limit + 1`` bytes so an oversized body is never fully loaded."""
    data = upload.file.read(limit + 1)
    if len(data) > limit:
        raise HTTPException(
            status_code=413,
            detail=f"{label} exceeds the {limit // (1024 * 1024)} MiB upload limit",
        )
    return data


def _validate_dimensions(
    width: int,
    height: int,
    *,
    label: str,
    settings: MediaIngestSettings | None = None,
) -> None:
    settings = settings or _ingest_settings()
    if width < 1 or height < 1:
        raise HTTPException(status_code=422, detail=f"{label} has invalid dimensions")
    if (width > settings.max_frame_dimension
            or height > settings.max_frame_dimension):
        raise HTTPException(
            status_code=413,
            detail=(f"{label} dimensions {width}x{height} exceed the "
                    f"{settings.max_frame_dimension}px side limit"),
        )
    if width * height > settings.max_frame_pixels:
        raise HTTPException(
            status_code=413,
            detail=(f"{label} has {width * height} pixels; "
                    f"limit is {settings.max_frame_pixels}"),
        )


def _decode_image(
    data: bytes,
    *,
    label: str,
    settings: MediaIngestSettings | None = None,
) -> np.ndarray:
    settings = settings or _ingest_settings()
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(io.BytesIO(data)) as source:
                _validate_dimensions(
                    source.width, source.height, label=label, settings=settings
                )
                source.load()
                return np.array(source.convert("RGB"), dtype=np.uint8, copy=True)
    except HTTPException:
        raise
    except (Image.DecompressionBombError, Image.DecompressionBombWarning,
            UnidentifiedImageError, OSError, ValueError) as exc:
        raise HTTPException(
            status_code=422, detail=f"couldn't decode {label} as an image") from exc


def load_image_upload(
    upload: UploadFile, *, settings: MediaIngestSettings | None = None
) -> np.ndarray:
    """Bounded single-image loader reused by review/draw-key endpoints."""
    settings = settings or _ingest_settings()
    label = upload.filename or "image"
    return _decode_image(
        _read_upload_limited(upload, settings.max_image_bytes, label=label),
        label=label,
        settings=settings,
    )


def _load_keys(
    uploads: List[UploadFile], *, settings: MediaIngestSettings | None = None
) -> List[np.ndarray]:
    """Read uploaded PNG files (sorted by filename) into numpy HxWx3 arrays."""
    settings = settings or _ingest_settings()
    if len(uploads) > settings.max_keys:
        raise HTTPException(
            status_code=413,
            detail=(f"too many image frames: got {len(uploads)}, "
                    f"limit is {settings.max_keys}"),
        )
    ordered = sorted(uploads, key=lambda u: u.filename or "")
    keys = []
    total_bytes = 0
    total_pixels = 0
    expected_shape = None
    for u in ordered:
        label = u.filename or "image"
        data = _read_upload_limited(u, settings.max_image_bytes, label=label)
        total_bytes += len(data)
        if total_bytes > settings.max_image_total_bytes:
            raise HTTPException(
                status_code=413,
                detail=(f"image batch exceeds the "
                        f"{settings.max_image_total_bytes // (1024 * 1024)} "
                        "MiB total limit"),
            )
        image = _decode_image(data, label=label, settings=settings)
        total_pixels += image.shape[0] * image.shape[1]
        if total_pixels > settings.max_key_total_pixels:
            raise HTTPException(
                status_code=413,
                detail=(f"image batch has {total_pixels} decoded pixels; "
                        f"limit is {settings.max_key_total_pixels}"),
            )
        if expected_shape is None:
            expected_shape = image.shape
        elif image.shape != expected_shape:
            raise HTTPException(
                status_code=422,
                detail=(f"all key frames must have the same dimensions; "
                        f"expected {expected_shape[1]}x{expected_shape[0]}, "
                        f"got {image.shape[1]}x{image.shape[0]} for {label}"),
            )
        keys.append(image)
    return keys


def load_stored_keys(
    blobs: "List[tuple[str, bytes]]", *, settings: MediaIngestSettings | None = None
) -> List[np.ndarray]:
    """Decode already-published key PNGs, in the order given.

    Resume reads these back from durable storage. Unlike `_load_keys` the order
    is the caller's (the snapshot's key index), never the filename — `key_10.png`
    sorts before `key_2.png`. The size ceilings still apply: these bytes are
    fetched from object storage, and a session's own artifacts are no more
    trustworthy as memory pressure than an upload is.
    """
    settings = settings or _ingest_settings()
    if len(blobs) > settings.max_keys:
        raise HTTPException(
            status_code=413,
            detail=(f"too many stored key frames: got {len(blobs)}, "
                    f"limit is {settings.max_keys}"),
        )
    keys: List[np.ndarray] = []
    total_pixels = 0
    for label, data in blobs:
        image = _decode_image(data, label=label, settings=settings)
        total_pixels += image.shape[0] * image.shape[1]
        if total_pixels > settings.max_key_total_pixels:
            raise HTTPException(
                status_code=413,
                detail=(f"stored key frames have {total_pixels} decoded pixels; "
                        f"limit is {settings.max_key_total_pixels}"),
            )
        keys.append(image)
    return keys


def _load_frames_from_video(
    upload: UploadFile,
    stride: int,
    *,
    settings: MediaIngestSettings | None = None,
) -> "tuple[List[np.ndarray], int, int, float]":
    """Decode a dropped video and keep every `stride`-th frame as a key. A slightly-long clip
    is AUTO-FIT (the stride is coarsened up to `stride * AUTOFIT_MAX_FACTOR`) so a short cut
    that is a bit over the cap just runs. A clip still over MAX_KEYS at that ceiling is too long
    for one cut → it fails loudly with the exact stride to use (we refuse to silently decimate
    it to a sparse, unfaithful set). Returns
    `(keys, gt_frames, effective_stride, source_frame_count, source_fps)` — `gt_frames[g]` is
    the middle dropped frame of gap g (the compare artifact's ORIGINAL pane; all None at
    stride 1) and `source_fps` is the clip's
    native fps (cadence derivation reads it downstream). cv2 is imported lazily so the PNG
    /session path never depends on opencv. Raises HTTPException on a non-video, an undecodable
    clip, a too-long clip, or < 2 keys."""
    settings = settings or _ingest_settings()
    ctype = (upload.content_type or "").lower()
    name = (upload.filename or "").lower()
    # The browser sets video/mp4 from File.type, but curl / programmatic clients often send
    # application/octet-stream (or nothing) for an .mp4. Accept those + a known video extension;
    # cv2 is the real arbiter (a non-video that slips past here fails decode -> 422 below). We
    # only early-reject things that are clearly NOT video (e.g. an image/png drop).
    _VIDEO_EXTS = (".mp4", ".mov", ".webm", ".mkv", ".avi", ".m4v")
    looks_like_video = (
        ctype.startswith("video/")
        or ctype in ("application/octet-stream", "")
        or name.endswith(_VIDEO_EXTS)
    )
    if not looks_like_video:
        raise HTTPException(status_code=400, detail=f"expected a video file, got content-type {ctype!r}")
    if stride < 1:
        raise HTTPException(status_code=400, detail="stride must be >= 1")
    try:
        import cv2
    except ImportError:
        raise HTTPException(status_code=500, detail="video decoding unavailable (opencv not installed on the server)")

    data = _read_upload_limited(
        upload, settings.max_video_bytes, label=name or "video"
    )
    fd, tmp_path = tempfile.mkstemp(suffix=".mp4", prefix="copilot_video_")
    cap = None
    try:
        with os.fdopen(fd, "wb") as fh:
            fh.write(data)
        cap = cv2.VideoCapture(tmp_path)
        if not cap.isOpened():
            raise HTTPException(status_code=422, detail="couldn't decode this video — is it an H.264 .mp4?")
        src_fps = cap.get(cv2.CAP_PROP_FPS) or 24.0
        reported_width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH) or 0)
        reported_height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT) or 0)
        if reported_width and reported_height:
            _validate_dimensions(
                reported_width,
                reported_height,
                label="video frame",
                settings=settings,
            )
        max_stride = stride * settings.autofit_max_factor
        keys: List[np.ndarray] = []
        expected_key_shape = None
        eff_stride = stride          # light auto-coarsening below, capped at max_stride
        idx = 0
        overflow = False             # too long even at the ceiling — keep counting, then error
        while True:
            ret, frame = cap.read()
            if not ret:
                break
            if idx >= settings.max_video_frames:
                raise HTTPException(
                    status_code=413,
                    detail=(f"video exceeds the {settings.max_video_frames}-frame "
                            "decode limit; "
                            f"trim it to a single short cut"),
                )
            height, width = frame.shape[:2]
            _validate_dimensions(
                width,
                height,
                label=f"video frame {idx}",
                settings=settings,
            )
            if not overflow and idx % eff_stride == 0:
                rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                key = np.asarray(rgb, dtype=np.uint8)
                if expected_key_shape is None:
                    expected_key_shape = key.shape
                elif key.shape != expected_key_shape:
                    raise HTTPException(
                        status_code=422,
                        detail=("all retained video frames must have the same "
                                f"dimensions; expected {expected_key_shape[1]}x"
                                f"{expected_key_shape[0]}, got {key.shape[1]}x"
                                f"{key.shape[0]} at frame {idx}"),
                    )
                keys.append(key)
                if len(keys) > settings.max_keys:
                    if eff_stride * 2 <= max_stride:
                        # light auto-fit: coarsen one notch. Double the stride and drop every
                        # 2nd kept frame; the survivors stay on the NEW (doubled) stride grid,
                        # so `idx % eff_stride` stays consistent. Memory stays <= MAX_KEYS+1.
                        eff_stride *= 2
                        del keys[1::2]
                    else:
                        # past the auto-fit ceiling: stop collecting, free the buffer, and just
                        # keep counting frames so we can report the exact stride needed.
                        overflow = True
                        keys = []
                if (keys and len(keys) * key.shape[0] * key.shape[1]
                        > settings.max_key_total_pixels):
                    raise HTTPException(
                        status_code=413,
                        detail=("retained video keys exceed the decoded-pixel "
                                f"limit of {settings.max_key_total_pixels}"),
                    )
            idx += 1

        # --- second pass: the middle dropped frame of each gap, for the compare
        # artifact's ORIGINAL pane. Runs before the finally-block deletes the tmp
        # file. eff_stride is final here, so key g sits at frame g*eff_stride and
        # the gap's middle at g*eff_stride + eff_stride//2. Bounded: <= len(keys)-1
        # extra frames (MAX_KEYS-capped). eff_stride == 1 drops nothing -> all None.
        gt_frames: "List[np.ndarray | None]" = [None] * max(len(keys) - 1, 0)
        if not overflow and eff_stride >= 2 and len(keys) >= 2:
            wanted = {g * eff_stride + eff_stride // 2: g
                      for g in range(len(keys) - 1)}
            cap.release()
            cap = cv2.VideoCapture(tmp_path)
            frame_no = 0
            while wanted and cap.isOpened():
                ret, frame = cap.read()
                if not ret:
                    break
                gap = wanted.pop(frame_no, None)
                if gap is not None:
                    rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                    gt_frames[gap] = np.asarray(rgb, dtype=np.uint8)
                frame_no += 1
    finally:
        if cap is not None:
            cap.release()          # deterministic release even if cv2.read() raised mid-loop
        try:
            os.remove(tmp_path)
        except OSError:
            pass

    if overflow:
        min_stride = max(
            stride + 1,
            (idx + settings.max_keys - 1) // settings.max_keys,
        )
        secs = idx / src_fps if src_fps else 0
        raise HTTPException(
            status_code=422,
            detail=(f"this clip is {idx} frames (~{secs:.0f}s) — too long to keep as keys. "
                    f"Auto-fit only coarsens up to stride {max_stride} "
                    f"(cap {settings.max_keys} keys), and "
                    f"sparser keys would have gaps too large to in-between faithfully. Trim it to a "
                    f"single short cut, or raise STRIDE to >= {min_stride}."),
        )
    if len(keys) < 2:
        raise HTTPException(
            status_code=422,
            detail=f"need at least 2 keyframes after decimation; got {len(keys)} (stride={eff_stride}, frames={idx})",
        )
    if eff_stride != stride:
        # surfaced in uvicorn.log — the clip was lightly auto-decimated to fit the MAX_KEYS ceiling
        print(f"[session/video] auto-fit stride {stride} -> {eff_stride} "
              f"({idx} frames -> {len(keys)} keys, cap {settings.max_keys})", flush=True)
    return keys, gt_frames, eff_stride, idx, src_fps
