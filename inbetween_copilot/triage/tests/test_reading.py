"""Reading the two key drawings of a refused pair.

A gate-refused pair was diagnosed from three scalars and nothing ever looked at
the drawings, so the brief could not name the hand that enters the frame. These
pin the split: the measurement says WHERE, the vision model says WHAT, and a key
budget the vision model moved must never be mistakable for one the calibrated
signals produced.
"""
from __future__ import annotations

import numpy as np

from inbetween_copilot.triage.reading import (
    KeyReading,
    adjust_keys,
    hot_cell,
    read_keys,
)


def _paper(size=180):
    return np.full((size, size, 3), 250, np.uint8)


def _with_ink(cells, size=180):
    """Draw a blob in each named 3x3 cell."""
    frame = _paper(size)
    names = {"tl": (0, 0), "tc": (0, 1), "tr": (0, 2),
             "ml": (1, 0), "mc": (1, 1), "mr": (1, 2),
             "bl": (2, 0), "bc": (2, 1), "br": (2, 2)}
    third = size // 3
    for cell in cells:
        row, col = names[cell]
        y, x = row * third + third // 4, col * third + third // 4
        frame[y:y + third // 2, x:x + third // 2] = 20
    return frame


def test_a_change_in_one_cell_is_localized_there():
    before = _paper()
    after = _with_ink(["bc"])          # a hand entering at the bottom centre
    found = hot_cell(before, after)
    assert found is not None, "a change confined to one cell was not localized"
    cell, score, ratio = found
    assert cell == "bc", found
    assert ratio >= 1.4 and score > 0


def test_a_change_spread_across_the_drawing_is_NOT_localized():
    """None is the honest answer; a top-1 of nine cells is a ranking."""
    before = _paper()
    after = _with_ink(["tl", "tc", "tr", "ml", "mc", "mr", "bl", "bc", "br"])
    assert hot_cell(before, after) is None


def test_identical_drawings_localize_nothing():
    frame = _with_ink(["mc"])
    assert hot_cell(frame, frame.copy()) is None


def test_a_dead_vision_model_costs_the_reading_not_the_diagnosis():
    def explode(prompt, frames):
        raise RuntimeError("vlm down")

    reading = read_keys(_paper(), _paper(), explode)
    assert reading.available is False
    assert read_keys(_paper(), _paper(), None).available is False


def test_a_malformed_answer_is_treated_as_no_reading():
    assert read_keys(_paper(), _paper(), lambda p, f: {}).available is False
    assert read_keys(_paper(), _paper(),
                     lambda p, f: {"note": "hi"}).available is False


def test_the_reading_is_typed_and_bounded():
    reading = read_keys(_paper(), _paper(), lambda p, f: {
        "what_moved": "character's hand", "appears_abruptly": True,
        "difficulty": "not-a-level", "note": "the hand enters at the bottom"})
    assert reading.available and reading.what_moved == "character's hand"
    assert reading.appears_abruptly is True
    # an unknown level must fall back, never propagate
    assert reading.difficulty == "moderate"


def test_an_abrupt_entrance_asks_for_one_more_key_and_says_why():
    reading = KeyReading(available=True, what_moved="hand", appears_abruptly=True)
    adjusted, why = adjust_keys(2, reading)
    assert adjusted == 3
    assert "abruptly" in why


def test_the_adjustment_never_leaves_the_calibrated_band():
    hard = KeyReading(available=True, difficulty="complex")
    easy = KeyReading(available=True, difficulty="simple")
    assert adjust_keys(3, hard)[0] == 3, "went above the fitted 1..3 band"
    assert adjust_keys(1, easy)[0] == 1, "went below the fitted 1..3 band"


def test_no_reading_leaves_the_calibrated_budget_exactly_alone():
    adjusted, why = adjust_keys(2, KeyReading(available=False))
    assert (adjusted, why) == (2, ""), (
        "a budget must not move when nothing was read")


def test_a_reading_about_a_different_part_of_the_frame_is_not_confirmed():
    """Observed live: the measurement said `bc` (a hand entering) while the model
    described the head and shoulders. A budget must not move on that."""
    from inbetween_copilot.triage.reading import agrees_with_measurement
    top = KeyReading(available=True, what_moved="head and shoulders", region="tc")
    assert agrees_with_measurement(top, ("bc", 0.11, 1.8)) is False


def test_a_touching_cell_counts_as_agreement():
    from inbetween_copilot.triage.reading import agrees_with_measurement
    near = KeyReading(available=True, what_moved="hand", region="mc")
    assert agrees_with_measurement(near, ("bc", 0.11, 1.8)) is True


def test_nothing_to_compare_is_not_a_disagreement():
    from inbetween_copilot.triage.reading import agrees_with_measurement
    vague = KeyReading(available=True, what_moved="hand", region="whole")
    assert agrees_with_measurement(vague, ("bc", 0.11, 1.8)) is None
    pinned = KeyReading(available=True, what_moved="hand", region="bc")
    assert agrees_with_measurement(pinned, None) is None
