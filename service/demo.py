"""Decimate-vs-GT comparison video for the web demo-mode.

The artist workflow has no ground truth (the in-between is what's being generated),
so a "real vs RIFE" comparison only makes sense in DEMO mode: take a FULL ordered
cut, decimate it stride-2 (even = kept keys `src`, odd = hidden GT `gt`) to simulate
the artist, RIFE the mids between consecutive keys, then build one frame-synced
side-by-side mp4 (left = ORIGINAL src+gt, right = RECON src+rife) via reporting.compare.
"""
from __future__ import annotations

import os
from typing import Callable, List

import numpy as np

from inbetween_copilot.reporting.compare import build_comparison_frames, build_split_sequences


def _encode_h264(frames: List[np.ndarray], path: str, fps: int) -> str:
    """Encode frames to a browser-playable H.264/yuv420p mp4 (EVEN dims required)."""
    h, w = frames[0].shape[:2]
    h2, w2 = h - (h % 2), w - (w % 2)
    frames = [f[:h2, :w2] for f in frames]
    import imageio
    imageio.mimwrite(path, frames, fps=fps, codec="libx264",
                     pixelformat="yuv420p", macro_block_size=None)
    return path


def _decimate_rife(frames_full: List[np.ndarray], rife_engine: Callable):
    """Stride-2 decimate (even = kept keys, odd = hidden GT), RIFE the n-1 mids.
    `rife_engine(a, b)` returns `[a, mid, b]`; we take the mid."""
    if len(frames_full) < 3:
        raise ValueError("need >= 3 frames (>= 2 kept keys + >= 1 hidden GT)")
    src = frames_full[0::2]
    gt = frames_full[1::2]
    mids = [np.asarray(rife_engine(src[i], src[i + 1])[1], np.uint8)
            for i in range(len(src) - 1)]
    return src, gt, mids


def build_comparison_video(frames_full: List[np.ndarray], rife_engine: Callable,
                           out_dir: str, *, fps: int = 24, name: str = "compare.mp4") -> str:
    """Decimate stride-2, RIFE the mids, encode a side-by-side mp4 (default 24fps)."""
    src, gt, mids = _decimate_rife(frames_full, rife_engine)
    return _encode_h264(build_comparison_frames(src, gt, mids), os.path.join(out_dir, name), fps)


def build_demo_videos(frames_full: List[np.ndarray], rife_engine: Callable,
                      out_dir: str, *, fps: int = 24) -> dict:
    """One decimate+RIFE pass -> the side-by-side `compare.mp4` PLUS the two separate
    full-frame cuts (`original.mp4` = src+GT, `recon.mp4` = src+RIFE) the client
    before/after wipe needs. Returns the artifact basenames."""
    src, gt, mids = _decimate_rife(frames_full, rife_engine)
    original, recon = build_split_sequences(src, gt, mids)
    _encode_h264(build_comparison_frames(src, gt, mids), os.path.join(out_dir, "compare.mp4"), fps)
    _encode_h264(original, os.path.join(out_dir, "original.mp4"), fps)
    _encode_h264(recon, os.path.join(out_dir, "recon.mp4"), fps)
    return {"video": "compare.mp4", "original": "original.mp4", "recon": "recon.mp4"}
