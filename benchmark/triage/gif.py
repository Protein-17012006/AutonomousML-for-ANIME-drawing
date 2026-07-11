"""Build a looping GIF from a clip's PNG frames.

Extracted from `benchmark.kappa_study.build_packet` (Phase 2 de-tangle, 2026-06-25)
so triage no longer reaches into the archived kappa_study packet. The kappa_study
vertical (blocked human-kappa study) keeps its own copy in legacy/research/.
"""
from __future__ import annotations

import os

from PIL import Image


def build_gif(clip_dir: str, out_path: str, fps: int) -> None:
    frames = sorted(f for f in os.listdir(clip_dir) if f.lower().endswith(".png"))
    imgs = [Image.open(os.path.join(clip_dir, f)).convert("RGB") for f in frames]
    dur = int(round(1000 / fps))
    imgs[0].save(out_path, save_all=True, append_images=imgs[1:], duration=dur,
                 loop=0, optimize=True, disposal=2)
