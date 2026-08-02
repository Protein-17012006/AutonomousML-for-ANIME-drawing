"""Onion skin for a gate-refused pair: the two keys, and the travel between them.

A `needs_key` pair has no in-between, so it has no frame to annotate and the
review board showed an empty cell. But the two KEY DRAWINGS exist, and what the
artist actually needs to see is the distance the breakdown has to cover.

So this draws what an animator already reads on a lightbox: the unchanged line in
grey, where the drawing WAS in red, where it MOVED TO in blue, and — only when
the measurement pinned one — a box around the cell that changed most.

What it deliberately does NOT do is mark where to put a line. That is an
authored decision: where the arc peaks, how much ease, whether to smear. Nothing
here knows the arc the artist intends, and a mark saying "draw it here" would be
the system inventing a creative choice and presenting it as measurement.

PIL + numpy only, mirrors artifacts.py. NEVER raises: a pair that fails to
render is simply absent from the mapping.
"""
from __future__ import annotations

import os

import numpy as np
from PIL import Image, ImageDraw

_WAS = (215, 60, 60)          # key A only
_BECOMES = (50, 110, 220)     # key B only
# Held ink is LIGHT, not near-black. On line art either reads fine, but a dense
# or photographic frame counts most pixels as ink, and a dark held colour turns
# the whole cell into a black slab with the moving part invisible inside it.
# Light grey degrades to "a faint drawing under two coloured ones", which is
# what a lightbox looks like anyway.
_HELD = (176, 176, 176)
_PAPER = (255, 255, 255)
_MARK = (20, 160, 20)
_INK_LEVEL = 200              # below this counts as a drawn line

_CELLS = (("tl", "tc", "tr"), ("ml", "mc", "mr"), ("bl", "bc", "br"))


def _ink(frame: np.ndarray) -> np.ndarray:
    grey = np.asarray(frame)
    if grey.ndim == 3:
        grey = grey.mean(axis=2)
    return grey < _INK_LEVEL


def build_key_overlay(a, b, out_dir: str, index: int, cell: "str | None" = None) -> "str | None":
    """Write ``pair_<i>_keys.png`` and return its filename, or None on failure."""
    try:
        first, second = np.asarray(a), np.asarray(b)
        if first.shape[:2] != second.shape[:2]:
            return None
        height, width = first.shape[:2]
        ink_a, ink_b = _ink(first), _ink(second)
        canvas = np.full((height, width, 3), _PAPER, np.uint8)
        canvas[ink_a] = _WAS
        canvas[ink_b] = _BECOMES
        # Drawn last: a line both keys share is held, not moving, and must not
        # read as travel.
        canvas[ink_a & ink_b] = _HELD

        image = Image.fromarray(canvas)
        draw = ImageDraw.Draw(image)
        if cell:
            box = _cell_box(cell, width, height)
            if box is not None:
                x0, y0, x1, y1 = box
                draw.rectangle([x0 + 2, y0 + 2, x1 - 3, y1 - 3],
                               outline=_MARK, width=3)
        _legend(draw, width)
        name = f"pair_{index}_keys.png"
        image.save(os.path.join(out_dir, name))
        return name
    except Exception:
        return None


def _cell_box(cell: str, width: int, height: int):
    for row, names in enumerate(_CELLS):
        for col, name in enumerate(names):
            if name == cell:
                return (col * width // 3, row * height // 3,
                        (col + 1) * width // 3, (row + 1) * height // 3)
    return None


def _legend(draw: ImageDraw.ImageDraw, width: int) -> None:
    """Say which colour is which. An overlay nobody can decode is a decoration."""
    text = "red = this key   blue = next key   grey = held"
    length = int(draw.textlength(text))
    draw.rectangle([4, 4, 12 + length, 22], fill=(0, 0, 0))
    draw.text((8, 8), text, fill=(255, 255, 255))


def build_key_overlays(result, keys, out_dir: str, cells=None) -> "dict[int, str]":
    """One overlay per gate-refused pair. ``cells`` maps pair index -> measured cell."""
    out: dict[int, str] = {}
    cells = cells or {}
    try:
        for pair in result.pairs:
            if str(getattr(pair, "action", "")) != "needs_key":
                continue
            index = pair.index
            if index < 0 or index + 1 >= len(keys):
                continue
            name = build_key_overlay(
                keys[index], keys[index + 1], out_dir, index,
                cell=cells.get(index) or cells.get(str(index)),
            )
            if name is not None:
                out[index] = name
    except Exception:
        pass
    return out
