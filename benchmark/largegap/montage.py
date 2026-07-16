"""Build labeled evidence strips for selection and engine comparison.

Each dictionary entry becomes one row and each requested frame index becomes
one column.  The GT row is always first so montages remain comparable across
the pilot, full run, and tracked report evidence.
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw


def _thumb(frame: np.ndarray, max_w: int) -> Image.Image:
    image = Image.fromarray(frame)
    if image.width > max_w:
        image = image.resize((max_w, int(image.height * max_w / image.width)))
    return image


def strip(
    rows: dict[str, list[np.ndarray]],
    col_idx: list[int],
    out_jpg: Path | str,
    label_h: int = 18,
    max_w: int = 220,
) -> None:
    """Write a compact labeled grid as a JPEG evidence artifact."""
    if not rows:
        raise ValueError("rows must not be empty")
    if not col_idx:
        raise ValueError("col_idx must not be empty")
    if max_w < 1 or label_h < 1:
        raise ValueError("max_w and label_h must be positive")

    names = (["gt"] if "gt" in rows else []) + sorted(
        name for name in rows if name != "gt")
    try:
        thumbs = {
            name: [_thumb(rows[name][index], max_w) for index in col_idx]
            for name in names
        }
    except IndexError as exc:
        raise ValueError("a requested column is missing from one or more rows") from exc

    cell_w = max(image.width for images in thumbs.values() for image in images)
    cell_h = max(image.height for images in thumbs.values() for image in images)
    canvas = Image.new(
        "RGB",
        (cell_w * len(col_idx), (cell_h + label_h) * len(names)),
        (24, 24, 24),
    )
    draw = ImageDraw.Draw(canvas)
    for row_index, name in enumerate(names):
        y = row_index * (cell_h + label_h)
        draw.text((4, y + 2), f"{name}  cols={col_idx}", fill=(255, 255, 0))
        for column, image in enumerate(thumbs[name]):
            canvas.paste(image, (column * cell_w, y + label_h))

    destination = Path(out_jpg)
    destination.parent.mkdir(parents=True, exist_ok=True)
    canvas.save(destination, quality=85)
