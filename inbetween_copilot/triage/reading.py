"""What the two KEY DRAWINGS of a gate-refused pair actually show.

Until now a refused pair was diagnosed entirely from three scalars — `gap`,
`shift_frac`, `regime` — and the drawing brief was written by the director from
those numbers alone. No vision model ever looked at the two drawings, because
the VLM is only invoked on INTERPOLATED frames and a refused pair has none. So
the co-pilot could say "a pose snap with small motion" but never "the hand
enters the frame abruptly", which is the thing an artist can act on.

The work is split along measured strengths, the same split
`qa/perception.py` already states:

  WHERE   `hot_cell` — per-cell change between the two keys. Measured, numpy
          only. Returns None unless one cell genuinely stands out, because a
          top-1 of nine cells is a ranking, not a finding.
  WHAT    `read_keys` — the VLM names the body part and whether it appears
          abruptly. On a real refused pair it answered "character's hand …
          appears abruptly" identically three times running, and it was right —
          while its own region guess was one cell off the measured hot cell
          (ADR-0012: detail-blind at the resolution it sees).

Never raises: a dead VLM costs the reading, not the diagnosis.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from inbetween_copilot.signals.motion import gap_score

_CELLS = (("tl", "tc", "tr"), ("ml", "mc", "mr"), ("bl", "bc", "br"))

# A cell must beat the runner-up by this factor to count as localized. On the
# probe pair the hand cell scored 0.115 against 0.064 (x1.80); below such a
# margin the "hottest" cell is just the top of a flat ranking.
_OUTLIER_RATIO = 1.4

KEY_READING_PROMPT = (
    "These are TWO consecutive key drawings by an animator (A then B). No "
    "in-between exists yet. Say WHAT MOVED between them, naming the body part "
    "or object an animator would name. If something enters, leaves, or appears "
    "abruptly, say so. Judge how hard the change is to in-between. Also say "
    "roughly which third of the frame it is in.\n"
    'Return JSON: {"what_moved": "<short phrase>", "region": '
    '"tl|tc|tr|ml|mc|mr|bl|bc|br|whole", "appears_abruptly": true|false, '
    '"difficulty": "simple|moderate|complex", '
    '"note": "<one sentence an animator would use>"}'
)

_DIFFICULTY = ("simple", "moderate", "complex")


@dataclass(frozen=True)
class KeyReading:
    """What the VLM saw. `available` False means it could not be asked."""

    available: bool
    what_moved: str = ""
    appears_abruptly: bool = False
    difficulty: str = "moderate"
    note: str = ""
    # The model's own guess at the region. NOT used to locate anything — it is
    # measured unreliable at this resolution (ADR-0012), and on the probe pair
    # it was a cell off. It is kept for ONE purpose: checking whether the model
    # was looking at the same part of the drawing the measurement points at.
    region: str = ""


def agrees_with_measurement(reading: "KeyReading", located) -> "bool | None":
    """Is the model describing the part that actually changed?

    None when there is nothing to compare. Observed on a real refused pair: the
    measurement put the change at `bc` (a hand entering) while the model
    described "the boy's head and shoulders" — the top of the frame. A brief
    built from both then named one part and pointed at another, and the budget
    moved on a reading that was not about the thing that changed.
    """
    if not reading.available or not reading.region or located is None:
        return None
    if reading.region == "whole":
        return None
    here = _POSITION.get(reading.region)
    there = _POSITION.get(located[0])
    if here is None or there is None:
        return None
    # Chebyshev distance on the 3x3 grid: touching cells count as agreement,
    # because the model is coarse, not because disagreement is acceptable.
    return max(abs(here[0] - there[0]), abs(here[1] - there[1])) <= 1


_POSITION = {name: (row, col)
             for row, names in enumerate(_CELLS)
             for col, name in enumerate(names)}


def hot_cell(a, b) -> "tuple[str, float, float] | None":
    """The one cell where the two keys differ most, if it truly stands out.

    Returns (cell, score, ratio_over_runner_up) or None. None is a real answer:
    a change spread evenly over the drawing has no region to point at, and
    saying so beats drawing a box somewhere plausible.
    """
    first = np.asarray(a)
    second = np.asarray(b)
    if first.shape != second.shape or first.ndim < 2:
        return None
    height, width = first.shape[:2]
    if height < 3 or width < 3:
        return None
    scored = []
    for row in range(3):
        for col in range(3):
            y0, y1 = row * height // 3, (row + 1) * height // 3
            x0, x1 = col * width // 3, (col + 1) * width // 3
            try:
                score = float(gap_score(first[y0:y1, x0:x1], second[y0:y1, x0:x1]))
            except Exception:
                return None
            scored.append((_CELLS[row][col], score))
    scored.sort(key=lambda item: item[1], reverse=True)
    best, runner_up = scored[0], scored[1]
    if best[1] <= 0:
        return None                     # nothing changed anywhere
    if runner_up[1] <= 0:
        # Every other cell is untouched: the strongest localization there is,
        # not the weakest. Returning None here would have thrown away the one
        # case the artist most wants pointed at.
        return best[0], round(best[1], 4), float("inf")
    ratio = best[1] / runner_up[1]
    if ratio < _OUTLIER_RATIO:
        return None
    return best[0], round(best[1], 4), round(ratio, 2)


_CELL_WORDS = {
    "tl": "top left", "tc": "top centre", "tr": "top right",
    "ml": "middle left", "mc": "middle centre", "mr": "middle right",
    "bl": "bottom left", "bc": "bottom centre", "br": "bottom right",
}


def read_keys(a, b, vlm_fn, *, located=None) -> KeyReading:
    """Ask the vision model what changed between the two drawings.

    When the measurement has already localized the change, the model is POINTED
    AT IT rather than asked to find it. Both parts then do what they are good at
    instead of being hoped to coincide: measured on a real pair, the pixels put
    the change at `bc` (a hand entering) while the unguided model described the
    face at `mc` — both true of the drawings, but only one of them was the
    change, and a brief built from the wrong one sends the artist to redraw a
    face that barely moved.
    """
    if vlm_fn is None:
        return KeyReading(available=False)
    prompt = KEY_READING_PROMPT
    if located is not None and located[0] in _CELL_WORDS:
        prompt += (f"\nMeasured on the pixels, the change is concentrated in the "
                   f"{_CELL_WORDS[located[0]]} of the frame. Describe what is "
                   f"there and what happened to it. If nothing there changed, "
                   f'say so in "note" and describe what did.')
    try:
        raw = vlm_fn(prompt, [a, b]) or {}
    except Exception:
        return KeyReading(available=False)
    if not isinstance(raw, dict) or not raw.get("what_moved"):
        return KeyReading(available=False)
    difficulty = str(raw.get("difficulty") or "moderate").lower()
    region = str(raw.get("region") or "").lower()
    return KeyReading(
        available=True,
        what_moved=str(raw.get("what_moved"))[:120],
        appears_abruptly=bool(raw.get("appears_abruptly")),
        difficulty=difficulty if difficulty in _DIFFICULTY else "moderate",
        note=str(raw.get("note") or "")[:300],
        region=region if region in _POSITION or region == "whole" else "",
    )


def adjust_keys(base: int, reading: KeyReading) -> "tuple[int, str]":
    """Nudge the calibrated key budget by what the drawings show.

    Deliberately bounded and deliberately small. `keys_from_gap` was fitted on
    exactly this population — pairs the gate refused — so this moves WITHIN a
    calibrated band rather than inventing a new scale, by at most one key, and
    never outside 1..3. The caller records both numbers and this reason, so a
    budget the vision model changed can never look like one the signals
    produced.
    """
    if not reading.available:
        return base, ""
    if reading.difficulty == "complex" or reading.appears_abruptly:
        adjusted = min(3, base + 1)
        if adjusted != base:
            why = ("the drawings show something entering abruptly"
                   if reading.appears_abruptly
                   else "the vision model reads this change as complex")
            return adjusted, why
        return base, ""
    if reading.difficulty == "simple":
        adjusted = max(1, base - 1)
        if adjusted != base:
            return adjusted, "the vision model reads this change as simple"
    return base, ""
