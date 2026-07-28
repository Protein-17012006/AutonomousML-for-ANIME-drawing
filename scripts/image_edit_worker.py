"""Box-local DiffuEraser worker.

Run this app only on loopback. It invokes Long's already-installed official
DiffuEraser checkout in its own venv, pads a still image to the model's
22-frame temporal contract, and returns the middle repaired frame.
"""
from __future__ import annotations

import base64
import binascii
import io
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import threading
import time

import numpy as np
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from PIL import Image, UnidentifiedImageError
from pydantic import BaseModel, Field


MODEL = "diffueraser"
CONTEXT_FRAMES = 22
CONTEXT_FPS = 4
MAX_BODY_BYTES = 48 * 1024 * 1024
MAX_PIXELS = 16_777_216
MAX_SIDE = 8192


class ImageEditRequest(BaseModel):
    model: str = MODEL
    image: str
    mask: str
    seed: int = Field(default=2026, ge=0, le=2_147_483_647)


def _decode_png(payload: str, *, grayscale: bool) -> np.ndarray:
    try:
        raw = base64.b64decode(payload, validate=True)
        with Image.open(io.BytesIO(raw)) as image:
            if (
                image.width < 1
                or image.height < 1
                or image.width > MAX_SIDE
                or image.height > MAX_SIDE
                or image.width * image.height > MAX_PIXELS
            ):
                raise ValueError("image dimensions exceed the worker limit")
            image.load()
            mode = "L" if grayscale else "RGB"
            return np.array(image.convert(mode), dtype=np.uint8, copy=True)
    except (
        binascii.Error,
        TypeError,
        ValueError,
        UnidentifiedImageError,
        OSError,
    ) as exc:
        raise ValueError("payload is not a valid bounded PNG") from exc


def _png_b64(image: np.ndarray) -> str:
    buffer = io.BytesIO()
    Image.fromarray(np.asarray(image, dtype=np.uint8)).save(buffer, format="PNG")
    return base64.b64encode(buffer.getvalue()).decode("ascii")


class DiffuEraserRunner:
    """Serialized subprocess adapter around the external model environment."""

    def __init__(self):
        self._lock = threading.Lock()

    @staticmethod
    def _root() -> Path:
        return Path(
            os.environ.get(
                "COPILOT_DIFFUERASER_ROOT",
                str(
                    Path.home()
                    / "Desktop"
                    / "anime_archive"
                    / "diffueraser_pipeline"
                ),
            )
        ).expanduser().resolve()

    @classmethod
    def _python(cls) -> Path:
        configured = os.environ.get("COPILOT_DIFFUERASER_PYTHON")
        if configured:
            return Path(configured).expanduser().resolve()
        return cls._root() / "diffueraser-venv" / "bin" / "python"

    @staticmethod
    def _ffmpeg() -> str:
        return os.environ.get("COPILOT_FFMPEG", "ffmpeg")

    @staticmethod
    def _timeout_seconds() -> float:
        try:
            value = float(
                os.environ.get("COPILOT_DIFFUERASER_TIMEOUT", "900")
            )
        except ValueError as exc:
            raise RuntimeError(
                "COPILOT_DIFFUERASER_TIMEOUT must be a number"
            ) from exc
        if value < 1:
            raise RuntimeError("COPILOT_DIFFUERASER_TIMEOUT must be >= 1")
        return value

    @classmethod
    def available(cls) -> bool:
        root = cls._root()
        return (
            cls._python().is_file()
            and (root / "run_diffueraser.py").is_file()
            and shutil.which(cls._ffmpeg()) is not None
        )

    @staticmethod
    def _run(command: list[str], *, cwd: Path, timeout: float) -> None:
        try:
            process = subprocess.run(
                command,
                cwd=str(cwd),
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                timeout=timeout,
                check=False,
            )
        except subprocess.TimeoutExpired as exc:
            raise RuntimeError("DiffuEraser inference timed out") from exc
        if process.returncode != 0:
            tail = (process.stdout or "")[-3000:]
            print(
                f"[image-edit-worker] command failed ({process.returncode})\n{tail}",
                file=sys.stderr,
                flush=True,
            )
            raise RuntimeError(
                f"DiffuEraser command failed with status {process.returncode}"
            )

    def _encode_sequence(
        self,
        frames_dir: Path,
        output_path: Path,
        *,
        timeout: float,
    ) -> None:
        self._run(
            [
                self._ffmpeg(),
                "-hide_banner",
                "-loglevel",
                "error",
                "-y",
                "-framerate",
                str(CONTEXT_FPS),
                "-i",
                str(frames_dir / "%04d.png"),
                "-c:v",
                "libx264",
                "-preset",
                "fast",
                "-crf",
                "0",
                "-pix_fmt",
                "yuv420p",
                "-r",
                str(CONTEXT_FPS),
                str(output_path),
            ],
            cwd=frames_dir.parent,
            timeout=timeout,
        )

    def run(
        self,
        image: np.ndarray,
        mask: np.ndarray,
        *,
        seed: int,
    ) -> np.ndarray:
        if image.shape[:2] != mask.shape:
            raise ValueError("image and mask dimensions must match")
        selected = mask > 8
        if not np.any(selected):
            raise ValueError("mask is empty")
        if not self.available():
            raise RuntimeError(
                "DiffuEraser checkout, venv, or ffmpeg is unavailable"
            )

        timeout = self._timeout_seconds()
        root = self._root()
        with self._lock, tempfile.TemporaryDirectory(
            prefix="copilot_image_edit_"
        ) as temporary:
            work = Path(temporary)
            frames_dir = work / "frames"
            masks_dir = work / "masks"
            output_dir = work / "output"
            frames_dir.mkdir()
            masks_dir.mkdir()
            output_dir.mkdir()

            source_image = Image.fromarray(image)
            mask_image = Image.fromarray(
                np.where(selected, 255, 0).astype(np.uint8)
            )
            for index in range(CONTEXT_FRAMES):
                source_image.save(frames_dir / f"{index:04d}.png")
                mask_image.save(masks_dir / f"{index:04d}.png")

            input_video = work / "input.mp4"
            mask_video = work / "mask.mp4"
            self._encode_sequence(frames_dir, input_video, timeout=timeout)
            self._encode_sequence(masks_dir, mask_video, timeout=timeout)

            duration = CONTEXT_FRAMES / CONTEXT_FPS
            self._run(
                [
                    str(self._python()),
                    "-u",
                    str(root / "run_diffueraser.py"),
                    "--input_video",
                    str(input_video),
                    "--input_mask",
                    str(mask_video),
                    "--video_length",
                    f"{duration:.3f}",
                    "--save_path",
                    str(output_dir),
                    "--max_img_size",
                    "960",
                    "--mask_dilation_iter",
                    "2",
                    "--neighbor_length",
                    "10",
                    "--ref_stride",
                    "5",
                    "--subvideo_length",
                    "60",
                    "--seed",
                    str(seed),
                    "--nframes",
                    str(CONTEXT_FRAMES),
                    "--refinement_passes",
                    "1",
                ],
                cwd=root,
                timeout=timeout,
            )

            result_video = output_dir / "diffueraser_result.mp4"
            if not result_video.is_file():
                raise RuntimeError("DiffuEraser did not create a result video")
            result_png = work / "result.png"
            self._run(
                [
                    self._ffmpeg(),
                    "-hide_banner",
                    "-loglevel",
                    "error",
                    "-y",
                    "-i",
                    str(result_video),
                    "-vf",
                    f"select=eq(n\\,{CONTEXT_FRAMES // 2})",
                    "-frames:v",
                    "1",
                    str(result_png),
                ],
                cwd=work,
                timeout=60,
            )
            with Image.open(result_png) as repaired_image:
                repaired_image.load()
                if repaired_image.size != (image.shape[1], image.shape[0]):
                    repaired_image = repaired_image.resize(
                        (image.shape[1], image.shape[0]),
                        Image.Resampling.BICUBIC,
                    )
                repaired = np.array(
                    repaired_image.convert("RGB"),
                    dtype=np.uint8,
                    copy=True,
                )

            # Preserve the same safety contract for callers that reach the
            # loopback worker directly.
            output = np.array(image, copy=True)
            output[selected] = repaired[selected]
            return output


app = FastAPI(title="Box Image Edit Worker")
_runner = DiffuEraserRunner()


@app.middleware("http")
async def _bounded_body(request: Request, call_next):
    raw_length = request.headers.get("content-length")
    if raw_length:
        try:
            if int(raw_length) > MAX_BODY_BYTES:
                return JSONResponse(
                    status_code=413,
                    content={"detail": "request body exceeds worker limit"},
                )
        except ValueError:
            return JSONResponse(
                status_code=400,
                content={"detail": "invalid content-length"},
            )
    return await call_next(request)


@app.get("/health")
def health():
    return {
        "status": "ok" if _runner.available() else "unavailable",
        "models": [MODEL] if _runner.available() else [],
        "busy": _runner._lock.locked(),
    }


@app.post("/edit")
def edit(request: ImageEditRequest):
    if request.model.strip().lower() != MODEL:
        raise HTTPException(
            status_code=422,
            detail=f"unsupported image-edit model: {request.model}",
        )
    try:
        image = _decode_png(request.image, grayscale=False)
        mask = _decode_png(request.mask, grayscale=True)
        started = time.monotonic()
        output = _runner.run(image, mask, seed=request.seed)
        return {
            "model": MODEL,
            "image": _png_b64(output),
            "elapsed_seconds": round(time.monotonic() - started, 3),
        }
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
