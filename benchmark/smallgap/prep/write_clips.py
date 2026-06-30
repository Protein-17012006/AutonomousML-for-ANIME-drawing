"""Write an assembled clip's frames as 0000.png.. and build a montage grid for
full-res adjudication."""
from __future__ import annotations

import os

import cv2
import numpy as np


def write_clip(frames, clip_dir: str) -> int:
    os.makedirs(clip_dir, exist_ok=True)
    for i, f in enumerate(frames):
        cv2.imwrite(os.path.join(clip_dir, f"{i:04d}.png"),
                    cv2.cvtColor(f, cv2.COLOR_RGB2BGR))
    return len(frames)


def montage(frames, cols: int = 8) -> np.ndarray:
    h, w = frames[0].shape[:2]
    rows = (len(frames) + cols - 1) // cols
    grid = np.zeros((rows * h, cols * w, 3), dtype=np.uint8)
    for i, f in enumerate(frames):
        r, c = divmod(i, cols)
        grid[r * h:(r + 1) * h, c * w:(c + 1) * w] = f
    return grid
