"""annotate_frame draws a cell-coarse red ellipse + label; writer emits per-pair PNGs."""
import os

import numpy as np
import pytest


def _flat(h=90, w=90):
    return np.full((h, w, 3), 200, np.uint8)


def _diff_mask(a, b):
    return np.any(a != b, axis=2)


def test_annotate_returns_new_array_same_shape_dtype():
    from service.media.annotate import annotate_frame
    f = _flat()
    out = annotate_frame(f, "br", "ghosting")
    assert out is not f
    assert out.shape == f.shape and out.dtype == f.dtype
    assert np.array_equal(f, _flat())          # input not mutated


def test_annotate_br_marks_bottom_right_cell():
    from service.media.annotate import annotate_frame
    f = _flat()
    out = annotate_frame(f, "br", "ghosting")
    d = _diff_mask(f, out)
    assert d[60:90, 60:90].any()               # ellipse inside the br cell
    assert not d[30:60, 0:30].any()            # ml cell untouched


def test_annotate_whole_draws_edge_ring_not_center():
    from service.media.annotate import annotate_frame
    f = _flat()
    out = annotate_frame(f, "whole", "flicker")
    d = _diff_mask(f, out)
    assert d[:12, :].any() and d[-12:, :].any()    # near top+bottom edges
    assert not d[40:50, 40:50].any()               # center clean


def test_annotate_unknown_hint_falls_back_to_ring():
    from service.media.annotate import annotate_frame
    f = _flat()
    out = annotate_frame(f, "not_a_hint", "ghosting")
    d = _diff_mask(f, out)
    assert d[:12, :].any() and not d[40:50, 40:50].any()


def test_annotate_label_chip_present():
    from service.media.annotate import annotate_frame
    f = _flat()
    out = annotate_frame(f, "br", "ghosting")
    # black chip pixels somewhere in the top strip (default chip corner)
    top = out[:24, :, :]
    assert (top == 0).all(axis=2).any()


class _Pair:
    def __init__(self, index, action="filled", frames=None):
        self.index = index
        self.action = action
        self.frames = frames if frames is not None else [_flat()] * 3


class _Result:
    def __init__(self, pairs):
        self.pairs = pairs


def test_writer_emits_png_per_explained_pair(tmp_path):
    from service.media.annotate import annotate_explained_pairs
    res = _Result([_Pair(0), _Pair(1)])
    ex = {1: {"err_type": "ghosting", "region": "mc", "explanation": "x"}}
    out = annotate_explained_pairs(res, ex, str(tmp_path))
    assert out == {1: "pair_1_annotated.png"}
    assert os.path.exists(tmp_path / "pair_1_annotated.png")


def test_writer_skips_frameless_and_never_raises(tmp_path):
    from service.media.annotate import annotate_explained_pairs
    res = _Result([_Pair(0, action="needs_key", frames=[])])
    ex = {0: {"err_type": "ghosting", "region": "mc", "explanation": "x"},
          7: {"err_type": "ghosting", "region": "mc", "explanation": "no such pair"}}
    assert annotate_explained_pairs(res, ex, str(tmp_path)) == {}


def test_writer_survives_malformed_result():
    """annotate_explained_pairs(None, ...) must return {} without raising."""
    from service.media.annotate import annotate_explained_pairs
    out = annotate_explained_pairs(None, {0: {"err_type": "x", "region": "mc"}}, "/tmp")
    assert out == {}


def test_writer_skips_pair_whose_frames_break_pil(tmp_path):
    """A pair with bad frames (non-image data) degrades; good pairs still write."""
    from service.media.annotate import annotate_explained_pairs
    # pair 0: bad frames (strings, not arrays)
    bad_pair = _Pair(0, frames=["not-an-image", "not-an-image", "not-an-image"])
    # pair 1: good frames
    good_pair = _Pair(1, frames=[_flat(), _flat(), _flat()])
    res = _Result([bad_pair, good_pair])
    ex = {
        0: {"err_type": "ghosting", "region": "mc"},
        1: {"err_type": "flicker", "region": "br"},
    }
    out = annotate_explained_pairs(res, ex, str(tmp_path))
    assert out == {1: "pair_1_annotated.png"}
    assert os.path.exists(tmp_path / "pair_1_annotated.png")
    # ensure bad pair did not write
    assert not os.path.exists(tmp_path / "pair_0_annotated.png")


def test_annotated_url_pattern_matches_session_static_route(tmp_path):
    # the writer's filename must compose with the /session/{sid}/{fname} static route
    from service.media.annotate import annotate_explained_pairs
    res = _Result([_Pair(2)])
    ex = {2: {"err_type": "warp_melt", "region": "br", "explanation": "x"}}
    files = annotate_explained_pairs(res, ex, str(tmp_path))
    assert files[2] == "pair_2_annotated.png"          # no path separators, url-safe
