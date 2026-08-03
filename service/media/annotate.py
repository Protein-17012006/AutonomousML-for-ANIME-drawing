"""Media adapter: burn the flag annotation into the in-between PNG (spec: vault
'2026-07-03 - Annotated-Circle Flag Demo - Design').

annotate_frame prefers a MEASURED region: `localize_softness` scores per-tile
sharpness of the interpolated frames against their own source frames on a 4x4
grid, and those tiles are boxed in red. That replaces relying on the VLM's 3x3
hint, which ADR-0012 records as unreliable — at 320 px the model is detail-blind
and spatial localization was deferred. In practice it answered `none` or `whole`,
so every mark was a ring around the entire drawing.

Without measured tiles it falls back to the hint: an ellipse in the named 3x3
cell, or a whole-frame ring when nothing was pinned. The label chip then reads
"not pinned" rather than "whole" — a ring means "somewhere in here", and calling
that `whole` claims the defect spans the frame.

Everything here is TILE-COARSE; nothing may imply pixel accuracy. PIL only,
mirrors artifacts.py; pure (copies, never mutates).
"""
from __future__ import annotations

import os

import numpy as np
from PIL import Image, ImageDraw

from service.media.explain import _HINT_GRID, region_box

_RED = (255, 40, 40)
_WHITE = (255, 255, 255)


def _label_chip(draw: ImageDraw.ImageDraw, w: int, text: str, hint: str) -> None:
    # default top-left; a top-left ("tl") ellipse would be covered -> go top-right
    tw = draw.textlength(text)
    x = (w - int(tw) - 12) if hint == "tl" else 4
    draw.rectangle([x, 4, x + int(tw) + 8, 22], fill=(0, 0, 0))
    draw.text((x + 4, 8), text, fill=_WHITE)


def region_label(hint: str, tiles: "dict | None") -> str:
    """What the mark is actually claiming.

    `none` used to render as `whole`, which asserts the defect spans the frame —
    a different and unearned claim from "nothing was pinned".
    """
    if tiles and tiles.get("mask"):
        count = len(tiles["mask"])
        return f"{count} soft tile{'s' if count != 1 else ''}"
    if hint == "whole":
        return "whole"
    if hint in _HINT_GRID:
        return hint
    return "not pinned"


def _tile_rects(tiles: dict, w: int, h: int):
    """Pixel rectangles for a measured tile mask, merged per contiguous run."""
    grid = int(tiles.get("grid") or 0)
    if grid <= 0:
        return []
    out = []
    for tile in tiles.get("mask") or []:
        try:
            row, col = int(tile[0]), int(tile[1])
        except (TypeError, ValueError, IndexError):
            continue
        if not (0 <= row < grid and 0 <= col < grid):
            continue
        out.append((col * w // grid, row * h // grid,
                    (col + 1) * w // grid, (row + 1) * h // grid))
    return out


def annotate_frame(frame: np.ndarray, hint: str, err_type: str,
                   tiles: "dict | None" = None) -> np.ndarray:
    arr = np.asarray(frame, dtype=np.uint8)
    h, w = arr.shape[:2]
    img = Image.fromarray(arr.copy())
    draw = ImageDraw.Draw(img)

    # A MEASURED region wins over the VLM's coarse hint: the model is
    # detail-blind at the resolution it sees (ADR-0012), while these tiles come
    # from per-tile sharpness of the interpolated frames themselves.
    rects = _tile_rects(tiles, w, h) if tiles else []
    if rects:
        for x0, y0, x1, y1 in rects:
            draw.rectangle([x0 + 1, y0 + 1, x1 - 2, y1 - 2], outline=_WHITE, width=1)
            draw.rectangle([x0 + 2, y0 + 2, x1 - 3, y1 - 3], outline=_RED, width=3)
    else:
        box = region_box(hint, w, h)
        if box is None or hint == "whole":
            # Nothing was pinned. The ring says "somewhere in here", and the
            # label must not upgrade that to "everywhere".
            draw.rectangle([3, 3, w - 4, h - 4], outline=_WHITE, width=1)
            draw.rectangle([5, 5, w - 6, h - 6], outline=_RED, width=3)
        else:
            x0, y0, x1, y1 = box
            # inset so the stroke stays inside the cell
            draw.ellipse([x0 + 2, y0 + 2, x1 - 3, y1 - 3], outline=_WHITE, width=1)
            draw.ellipse([x0 + 4, y0 + 4, x1 - 5, y1 - 5], outline=_RED, width=3)

    _label_chip(draw, w, f"{err_type} @ {region_label(hint, tiles)}", hint)
    return np.array(img, dtype=np.uint8)


def annotate_explained_pairs(result, explanations: dict, out_dir: str) -> dict:
    """Write pair_<i>_annotated.png for each explained pair that has frames.

    Returns {pair_index: filename}. NEVER raises (degrade-never-500): a pair
    that fails to annotate is simply absent from the mapping.
    """
    out: dict[int, str] = {}
    try:
        by_index = {p.index: p for p in result.pairs}
        for i, e in explanations.items():
            try:
                p = by_index.get(i)
                if p is None or p.action not in ("filled", "generated") or not p.frames:
                    continue
                mid = p.frames[len(p.frames) // 2]          # same frame save_pair_mid persists
                mid = mid if isinstance(mid, np.ndarray) else np.array(mid, dtype=np.uint8)
                ann = annotate_frame(mid, e.get("region", "none"),
                                     e.get("err_type", "defect"),
                                     tiles=e.get("region_tiles"))
                fname = f"pair_{i}_annotated.png"
                Image.fromarray(ann).save(os.path.join(out_dir, fname))
                out[i] = fname
            except Exception:
                continue
    except Exception:
        pass
    return out
