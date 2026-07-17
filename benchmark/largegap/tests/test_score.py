import math

import numpy as np
import pytest

from benchmark.largegap.score import aggregate, dup_mask, score_frames, win_rate


def _f(v):
    return np.full((8, 8, 3), v, dtype=np.uint8)


def test_dup_mask_marks_repeats():
    gt = [_f(10), _f(10), _f(50), _f(50), _f(90)]
    assert dup_mask(gt) == [False, True, False, True, False]


def test_identical_frames_cap_psnr_at_60():
    rows = score_frames([_f(10)] * 3, [_f(10)] * 3, mid_idx=[1], dup=[False] * 3)
    assert rows[0]["psnr"] == 60.0
    assert rows[0]["ssim"] == 1.0


def test_aggregate_excludes_held_from_hold_aware():
    rows = [
        {"idx": 1, "psnr": 60.0, "ssim": 1.0, "held": True},   # free copy
        {"idx": 2, "psnr": 20.0, "ssim": 0.5, "held": False},
    ]
    agg = aggregate(rows)
    assert agg["psnr_hold"] == 20.0 and agg["ssim_hold"] == 0.5
    assert agg["psnr_raw"] == 40.0
    assert agg["n_scored"] == 1 and agg["n_held"] == 1


def test_win_rate():
    a = [{"psnr_hold": 30.0}, {"psnr_hold": 10.0}, {"psnr_hold": 25.0}]
    b = [{"psnr_hold": 20.0}, {"psnr_hold": 20.0}, {"psnr_hold": 20.0}]
    assert win_rate(a, b) == 2 / 3


def test_win_rate_skips_none_pairs():
    a = [{"psnr_hold": None}, {"psnr_hold": 30.0}]
    b = [{"psnr_hold": 20.0}, {"psnr_hold": 20.0}]
    assert win_rate(a, b) == 1.0          # only the comparable pair counts


def test_win_rate_no_comparable_pairs_is_nan():
    assert math.isnan(win_rate([], []))
    assert math.isnan(win_rate([{"psnr_hold": None}], [{"psnr_hold": 1.0}]))


def test_score_frames_rejects_length_mismatch():
    with pytest.raises(ValueError, match="length mismatch"):
        score_frames([_f(1)], [_f(1), _f(2)], [0], [False])
