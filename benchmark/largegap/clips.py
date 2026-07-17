"""Eval-clip preparation: decode -> trim to 65 -> deterministic filters ->
re-encode ONE canonical eval.mp4 -> canonical PNG frames decoded from it.

Every engine's inputs derive from the SAME eval.mp4 (LDF reads the mp4 and
self-decimates; local engines read the PNGs) so conditioning parity is exact
by construction. Hardsub heuristic is deliberately simple — the selection
montage (human veto, Task 10) is the final authority.
"""
from __future__ import annotations

import subprocess
import tempfile
from pathlib import Path

import cv2
import numpy as np

from benchmark.lib.signals.motion_primitives import gap_score
from benchmark.smallgap.interp.regime import scene_cut

TRIM_FRAMES = 65            # 4*16 + 1: exact end key for every tsf in {2,4,8,16}
WINDOW_STRIDE = 16          # scan long scenes; do not assume motion is in frame 0..64
FLASH_RATIO = 4.0           # step > ratio * median(step) -> flash/spike
HARDSUB_MAX = 0.02          # bright-pixel fraction of the bottom band
MOTION_MIN = 0.01           # mean consecutive gap_score floor


def decode_video(path: Path | str,
                 max_frames: int | None = TRIM_FRAMES) -> list[np.ndarray]:
    cap = cv2.VideoCapture(str(path))
    if not cap.isOpened():
        cap.release()
        raise RuntimeError(f"cannot open video: {path}")
    frames: list[np.ndarray] = []
    while max_frames is None or len(frames) < max_frames:
        ok, bgr = cap.read()
        if not ok:
            break
        frames.append(cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB))
    cap.release()
    return frames


def _ffmpeg_exe() -> str:
    import imageio_ffmpeg
    return imageio_ffmpeg.get_ffmpeg_exe()


def write_eval_clip(frames: list[np.ndarray], out_mp4: Path | str,
                    fps: int = 24, pix_fmt: str = "yuv444p") -> None:
    out_mp4 = Path(out_mp4)
    out_mp4.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as td:
        for i, f in enumerate(frames):
            cv2.imwrite(str(Path(td) / f"{i:05d}.png"),
                        cv2.cvtColor(f, cv2.COLOR_RGB2BGR))
        subprocess.run(
            [_ffmpeg_exe(), "-y", "-framerate", str(fps),
             "-i", str(Path(td) / "%05d.png"),
             "-c:v", "libx264", "-crf", "0", "-pix_fmt", pix_fmt,
             str(out_mp4)],
            check=True, capture_output=True)


def motion_steps(frames: list[np.ndarray]) -> list[float]:
    return [gap_score(a, b) for a, b in zip(frames, frames[1:])]


def hardsub_score(frames: list[np.ndarray]) -> float:
    """Median fraction of near-white pixels in the bottom 25% band.

    Vietsub hardsubs are bright text on a dark outline pinned to the bottom;
    clean anime rarely keeps a bright static band there. Coarse on purpose.
    """
    vals = []
    for f in frames[::4]:
        band = f[int(f.shape[0] * 0.75):]
        g = band.astype(np.float32).mean(axis=2)
        vals.append(float((g > 210).mean()))
    return float(np.median(vals))


def clip_flags(frames: list[np.ndarray]) -> dict:
    steps = motion_steps(frames)
    med = max(float(np.median(steps)), 1e-4)
    return {
        "motion_mean": float(np.mean(steps)),
        "motion_max": float(np.max(steps)),
        "has_cut": any(scene_cut(a, b) for a, b in zip(frames, frames[1:])),
        "has_flash": float(np.max(steps)) > FLASH_RATIO * med,
        "hardsub": hardsub_score(frames),
    }


def _candidate_starts(n_frames: int, window: int = TRIM_FRAMES,
                      stride: int = WINDOW_STRIDE) -> list[int]:
    if n_frames < window:
        return []
    last = n_frames - window
    return sorted(set(range(0, last + 1, stride)) | {last})


def best_window(frames: list[np.ndarray], window: int = TRIM_FRAMES,
                stride: int = WINDOW_STRIDE) -> tuple[list[np.ndarray], int, dict]:
    """Pick the highest-motion clean window from a pre-cut source scene.

    TransNet scenes can be hundreds of frames long and often open on a hold.
    Looking only at frames 0..64 made the real Clevatess OOD pool appear
    entirely static.  Candidate filtering is progressive: prefer windows with
    no cut, then no flash, then no hardsubs, and maximize motion only after
    those validity constraints.  If no candidate passes a constraint, return
    the best remaining one so ``select_clip`` records the honest drop reason.
    """
    starts = _candidate_starts(len(frames), window, stride)
    if not starts:
        raise ValueError(f"need at least {window} frames, got {len(frames)}")
    assessed = [
        (start, clip_flags(frames[start:start + window]))
        for start in starts
    ]
    eligible = assessed
    for valid in (
        lambda flags: not flags["has_cut"],
        lambda flags: not flags["has_flash"],
        lambda flags: flags["hardsub"] <= HARDSUB_MAX,
    ):
        passing = [(start, flags) for start, flags in eligible if valid(flags)]
        if passing:
            eligible = passing
        else:
            break
    start, flags = max(eligible, key=lambda item: item[1]["motion_mean"])
    return frames[start:start + window], start, flags


def select_clip(src: Path | str, clip_id: str, tier: str, out_dir: Path | str,
                motion_min: float = MOTION_MIN) -> dict:
    row: dict = {"clip_id": clip_id, "tier": tier, "src": str(src)}
    try:
        source_frames = decode_video(src, max_frames=None)
    except RuntimeError as e:
        return row | {"kept": False, "drop_reason": "decode_error",
                      "n_frames_used": 0, "error": str(e)}
    if len(source_frames) < TRIM_FRAMES:
        return row | {"kept": False, "drop_reason": "too_short",
                      "n_frames_used": len(source_frames),
                      "source_n_frames": len(source_frames)}
    frames, start_frame, flags = best_window(source_frames)
    row |= flags | {"n_frames_used": TRIM_FRAMES,
                    "source_n_frames": len(source_frames),
                    "start_frame": start_frame}
    for cond, reason in [(flags["has_cut"], "scene_cut"),
                         (flags["has_flash"], "flash"),
                         (flags["hardsub"] > HARDSUB_MAX, "hardsub"),
                         (flags["motion_mean"] < motion_min, "low_motion")]:
        if cond:
            return row | {"kept": False, "drop_reason": reason}
    clip_dir = Path(out_dir) / clip_id
    write_eval_clip(frames, clip_dir / "eval.mp4")
    canonical = decode_video(clip_dir / "eval.mp4", max_frames=TRIM_FRAMES)
    fdir = clip_dir / "frames"
    fdir.mkdir(parents=True, exist_ok=True)
    for i, f in enumerate(canonical):
        cv2.imwrite(str(fdir / f"{i:05d}.png"), cv2.cvtColor(f, cv2.COLOR_RGB2BGR))
    return row | {"kept": True, "drop_reason": None}
