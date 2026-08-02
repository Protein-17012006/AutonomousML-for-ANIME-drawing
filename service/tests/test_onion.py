"""The two keys of a refused pair, and the travel between them.

A `needs_key` pair has no in-between to annotate, so the review board's middle
cell was empty and the artist was told "there is no annotated image" — true, and
no help at all. The two KEY DRAWINGS exist; this shows the distance the
breakdown has to cover.
"""
from __future__ import annotations

import numpy as np
from PIL import Image

from service.media.onion import build_key_overlay, build_key_overlays


def _paper(size=120):
    return np.full((size, size, 3), 250, np.uint8)


def _with_bar(y, x, size=120):
    frame = _paper(size)
    frame[y:y + 20, x:x + 8] = 20
    return frame


def _colours(path):
    pixels = np.array(Image.open(path).convert("RGB"))
    body = pixels[26:]                       # below the legend chip
    return {
        "was": bool(((body[..., 0] > 180) & (body[..., 2] < 110)).any()),
        "becomes": bool(((body[..., 2] > 180) & (body[..., 0] < 110)).any()),
        # held ink is a neutral grey: all channels close together and mid-toned
        "held": bool((((body.max(axis=2).astype(int)
                        - body.min(axis=2).astype(int)) < 12)
                      & (body.max(axis=2) > 120)
                      & (body.max(axis=2) < 220)).any()),
    }


def test_a_line_that_moved_is_shown_twice_in_two_colours(tmp_path):
    name = build_key_overlay(_with_bar(40, 30), _with_bar(40, 70), str(tmp_path), 1)
    assert name == "pair_1_keys.png"
    found = _colours(tmp_path / name)
    assert found["was"] and found["becomes"], found
    assert not found["held"], "a line that moved must not read as held"


def test_a_line_that_did_not_move_reads_as_held(tmp_path):
    frame = _with_bar(40, 30)
    name = build_key_overlay(frame, frame.copy(), str(tmp_path), 0)
    found = _colours(tmp_path / name)
    assert found["held"], found
    assert not found["was"] and not found["becomes"], (
        "an unchanged line must not be drawn as travel")


def test_the_measured_cell_is_marked_and_an_unmeasured_one_is_not(tmp_path):
    marked = build_key_overlay(_with_bar(40, 30), _with_bar(40, 70),
                               str(tmp_path), 2, cell="br")
    plain = build_key_overlay(_with_bar(40, 30), _with_bar(40, 70),
                              str(tmp_path), 3)
    def green(path):
        pixels = np.array(Image.open(path).convert("RGB"))[26:]
        return bool(((pixels[..., 1] > 120)
                     & (pixels[..., 0] < 90) & (pixels[..., 2] < 90)).any())
    assert green(tmp_path / marked), "the measured cell was not marked"
    assert not green(tmp_path / plain), (
        "a box was drawn without a measurement to justify it")


def test_mismatched_drawings_degrade_instead_of_raising(tmp_path):
    assert build_key_overlay(_paper(120), _paper(64), str(tmp_path), 0) is None
    assert build_key_overlay("not an image", None, str(tmp_path), 0) is None


class _Pair:
    def __init__(self, index, action):
        self.index = index
        self.action = action


class _Result:
    def __init__(self, pairs):
        self.pairs = pairs


def test_only_gate_refused_pairs_get_an_overlay(tmp_path):
    keys = [_with_bar(40, 10), _with_bar(40, 40), _with_bar(40, 70)]
    result = _Result([_Pair(0, "filled"), _Pair(1, "needs_key")])
    out = build_key_overlays(result, keys, str(tmp_path), cells={1: "mc"})
    assert out == {1: "pair_1_keys.png"}, (
        "a filled pair already has a rendered in-between to look at")


def test_a_pair_without_both_keys_is_skipped(tmp_path):
    result = _Result([_Pair(5, "needs_key")])
    assert build_key_overlays(result, [_paper()], str(tmp_path)) == {}
