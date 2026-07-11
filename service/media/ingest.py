"""Media ingestion: turn uploads (PNG keys or a dropped video) into numpy key arrays."""
from __future__ import annotations

import io
import os
import tempfile
from typing import List

import numpy as np
from PIL import Image
from fastapi import HTTPException, UploadFile

# max key frames a decimated video may yield before we refuse the run (env-tunable).
# A finished cut at stride 2 can be thousands of keys; bound it so a dropped video
# can't pin the box for hours / exhaust memory.
MAX_KEYS = int(os.environ.get("COPILOT_MAX_KEYS", "100"))
# Auto-fit only coarsens the stride up to this factor of the user's stride. A clip that still
# overflows MAX_KEYS at stride*FACTOR is genuinely too long for ONE cut: rather than silently
# decimate it to a sparse, unfaithful set (gaps too large to interpolate → mostly needs-key),
# we fail loudly with the exact stride to use / advice to trim. Keeps "drop a short cut → it
# just runs" while refusing to misrepresent a long montage.
AUTOFIT_MAX_FACTOR = int(os.environ.get("COPILOT_AUTOFIT_MAX_FACTOR", "4"))


def _load_keys(uploads: List[UploadFile]) -> List[np.ndarray]:
    """Read uploaded PNG files (sorted by filename) into numpy HxWx3 arrays."""
    ordered = sorted(uploads, key=lambda u: u.filename or "")
    keys = []
    for u in ordered:
        data = u.file.read()
        img = Image.open(io.BytesIO(data)).convert("RGB")
        keys.append(np.array(img, dtype=np.uint8))
    return keys


def _load_frames_from_video(upload: UploadFile, stride: int) -> "tuple[List[np.ndarray], int, int, float]":
    """Decode a dropped video and keep every `stride`-th frame as a key. A slightly-long clip
    is AUTO-FIT (the stride is coarsened up to `stride * AUTOFIT_MAX_FACTOR`) so a short cut
    that is a bit over the cap just runs. A clip still over MAX_KEYS at that ceiling is too long
    for one cut → it fails loudly with the exact stride to use (we refuse to silently decimate
    it to a sparse, unfaithful set). Returns
    `(keys, effective_stride, source_frame_count, source_fps)` — `source_fps` is the clip's
    native fps (cadence derivation reads it downstream). cv2 is imported lazily so the PNG
    /session path never depends on opencv. Raises HTTPException on a non-video, an undecodable
    clip, a too-long clip, or < 2 keys."""
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

    data = upload.file.read()
    fd, tmp_path = tempfile.mkstemp(suffix=".mp4", prefix="copilot_video_")
    cap = None
    try:
        with os.fdopen(fd, "wb") as fh:
            fh.write(data)
        cap = cv2.VideoCapture(tmp_path)
        if not cap.isOpened():
            raise HTTPException(status_code=422, detail="couldn't decode this video — is it an H.264 .mp4?")
        src_fps = cap.get(cv2.CAP_PROP_FPS) or 24.0
        max_stride = stride * AUTOFIT_MAX_FACTOR
        keys: List[np.ndarray] = []
        eff_stride = stride          # light auto-coarsening below, capped at max_stride
        idx = 0
        overflow = False             # too long even at the ceiling — keep counting, then error
        while True:
            ret, frame = cap.read()
            if not ret:
                break
            if not overflow and idx % eff_stride == 0:
                rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                keys.append(np.asarray(rgb, dtype=np.uint8))
                if len(keys) > MAX_KEYS:
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
            idx += 1
    finally:
        if cap is not None:
            cap.release()          # deterministic release even if cv2.read() raised mid-loop
        try:
            os.remove(tmp_path)
        except OSError:
            pass

    if overflow:
        min_stride = max(stride + 1, (idx + MAX_KEYS - 1) // MAX_KEYS)   # ceil(idx / MAX_KEYS)
        secs = idx / src_fps if src_fps else 0
        raise HTTPException(
            status_code=422,
            detail=(f"this clip is {idx} frames (~{secs:.0f}s) — too long to keep as keys. "
                    f"Auto-fit only coarsens up to stride {max_stride} (cap {MAX_KEYS} keys), and "
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
              f"({idx} frames -> {len(keys)} keys, cap {MAX_KEYS})", flush=True)
    return keys, eff_stride, idx, src_fps
