"""U4 helper -- one native-res montage per disagreement clip for the Claude-eyes
full-res adjudication pass. Tiles are upscaled so the short side is >= min_tile
(ADR-0012 bans montage tiles below 360px for fine judgment). Deterministic."""
from __future__ import annotations

import glob
import math

from PIL import Image


def build_montage(clip_dir, out_path, *, min_tile: int = 360, cols: int = 4) -> str:
    paths = sorted(glob.glob(clip_dir + "/*.png"))
    frames = [Image.open(p).convert("RGB") for p in paths]
    if not frames:
        raise ValueError(f"no frames in {clip_dir}")
    w, h = frames[0].size
    scale = max(1.0, min_tile / min(w, h))
    tw, th = int(round(w * scale)), int(round(h * scale))
    rows = math.ceil(len(frames) / cols)
    canvas = Image.new("RGB", (cols * tw, rows * th), (0, 0, 0))
    for i, fr in enumerate(frames):
        tile = fr.resize((tw, th), Image.NEAREST)
        canvas.paste(tile, ((i % cols) * tw, (i // cols) * th))
    canvas.save(out_path)
    return out_path
