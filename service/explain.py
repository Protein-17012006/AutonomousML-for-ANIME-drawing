"""Deep explainability for the in-between co-pilot service.

For each FLAGGED or ABSTAINED pair, surface the defect type + region +
a one-line explanation by calling perceive() with the structured VLM fn.
"""
from __future__ import annotations

from inbetween_copilot.qa.perception import perceive

# Maps the 3×3 grid hint to (col, row) position indices (0-based thirds).
_HINT_GRID: dict[str, tuple[int, int]] = {
    "tl": (0, 0), "tc": (1, 0), "tr": (2, 0),
    "ml": (0, 1), "mc": (1, 1), "mr": (2, 1),
    "bl": (0, 2), "bc": (1, 2), "br": (2, 2),
}


def region_box(hint: str, w: int, h: int) -> tuple | None:
    """Map a 3×3 region hint to a pixel bounding box (x0, y0, x1, y1).

    Returns (0, 0, w, h) for "whole", None for "none" or unknown hints.
    """
    if hint == "whole":
        return (0, 0, w, h)
    if hint not in _HINT_GRID:
        return None
    col, row = _HINT_GRID[hint]
    cw = w // 3
    ch = h // 3
    x0 = col * cw
    y0 = row * ch
    # Right/bottom edge uses exact thirds; last column/row clips to w/h.
    x1 = (col + 1) * cw if col < 2 else w
    y1 = (row + 1) * ch if row < 2 else h
    return (x0, y0, x1, y1)


def explain_pairs(result, *, vlm_struct_fn, softness_fn) -> dict[int, dict]:
    """For each FLAGGED or ABSTAINED pair with frames, call perceive() with the
    structured VLM fn and return a mapping of pair index -> explanation dict.

    Skips:
      - pairs whose action is "needs_key" (no frames to examine)
      - pairs with qa.status == "pass"
      - pairs without frames
    """
    out: dict[int, dict] = {}
    for p in result.pairs:
        if p.action not in ("filled", "generated"):
            continue
        if p.qa is None:
            continue
        if p.qa.status not in ("flag", "abstain"):
            continue
        if not p.frames:
            continue
        verdict = perceive(p.frames, vlm_fn=vlm_struct_fn, softness_fn=softness_fn)
        out[p.index] = {
            "err_type": verdict.err_type,
            "region": verdict.region_hint,
            "explanation": verdict.explanation,
        }
    return out
