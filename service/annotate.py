"""Burn the flag annotation into the in-between PNG (spec: vault
'2026-07-03 - Annotated-Circle Flag Demo - Design').

annotate_frame draws a red ellipse inscribed in the VLM's 3x3 region cell
(hint `whole`/`none`/unknown -> an inset ring around the whole frame: QA
flagged the pair but the VLM could not pin a cell) plus a short label chip
"{err_type} @ {shown-region}". Unknown hints are shown as `whole`. The circle
is CELL-COARSE — the VLM reports a region, not pixels — so nothing here may
imply pixel accuracy. PIL only, mirrors artifacts.py; pure (copies, never mutates).
"""
from __future__ import annotations

import os

import numpy as np
from PIL import Image, ImageDraw

from service.explain import region_box

_RED = (255, 40, 40)
_WHITE = (255, 255, 255)


def _label_chip(draw: ImageDraw.ImageDraw, w: int, text: str, hint: str) -> None:
    # default top-left; a top-left ("tl") ellipse would be covered -> go top-right
    tw = draw.textlength(text)
    x = (w - int(tw) - 12) if hint == "tl" else 4
    draw.rectangle([x, 4, x + int(tw) + 8, 22], fill=(0, 0, 0))
    draw.text((x + 4, 8), text, fill=_WHITE)


def annotate_frame(frame: np.ndarray, hint: str, err_type: str) -> np.ndarray:
    arr = np.asarray(frame, dtype=np.uint8)
    h, w = arr.shape[:2]
    img = Image.fromarray(arr.copy())
    draw = ImageDraw.Draw(img)

    box = region_box(hint, w, h)
    if box is None or hint == "whole":
        # whole-frame ring, inset a few px
        draw.rectangle([3, 3, w - 4, h - 4], outline=_WHITE, width=1)
        draw.rectangle([5, 5, w - 6, h - 6], outline=_RED, width=3)
        shown = "whole"
    else:
        x0, y0, x1, y1 = box
        # inset so the stroke stays inside the cell
        draw.ellipse([x0 + 2, y0 + 2, x1 - 3, y1 - 3], outline=_WHITE, width=1)
        draw.ellipse([x0 + 4, y0 + 4, x1 - 5, y1 - 5], outline=_RED, width=3)
        shown = hint

    _label_chip(draw, w, f"{err_type} @ {shown}", hint)
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
                ann = annotate_frame(mid, e.get("region", "none"), e.get("err_type", "defect"))
                fname = f"pair_{i}_annotated.png"
                Image.fromarray(ann).save(os.path.join(out_dir, fname))
                out[i] = fname
            except Exception:
                continue
    except Exception:
        pass
    return out
