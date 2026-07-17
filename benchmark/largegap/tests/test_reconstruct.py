import numpy as np
import pytest

from benchmark.largegap.span import plan_span
from benchmark.largegap.reconstruct import (
    blend_recon, fill_mids, hold_copy_recon, rife_recon,
)


def _keys(vals):
    """Constant-valued 4x4 RGB frames, one per scalar in vals."""
    return [np.full((4, 4, 3), v, dtype=np.uint8) for v in vals]


def test_hold_copy_repeats_previous_key():
    plan = plan_span(5, 2)                      # keys at 0,2,4
    r = hold_copy_recon(_keys([10, 20, 30]), plan)
    assert len(r) == 5
    assert r[0][0, 0, 0] == 10 and r[1][0, 0, 0] == 10   # mid 1 <- key A
    assert r[2][0, 0, 0] == 20 and r[3][0, 0, 0] == 20   # mid 3 <- key at 2
    assert r[4][0, 0, 0] == 30


def test_blend_is_linear_crossfade():
    plan = plan_span(5, 4)                      # keys at 0,4; mids 1..3
    r = blend_recon(_keys([0, 100]), plan)
    assert [r[i][0, 0, 0] for i in range(5)] == [0, 25, 50, 75, 100]


def test_fill_mids_recursion_order_and_count():
    def fake_engine(a, b):
        return [a, f"({a}|{b})", b]
    mids = fill_mids("A", "B", depth=2, engine=fake_engine)
    assert mids == ["(A|(A|B))", "(A|B)", "((A|B)|B)"]
    assert len(fill_mids("A", "B", 4, fake_engine)) == 15


def test_rife_recon_places_keys_and_mids():
    def avg_engine(a, b):
        return [a, ((a.astype(np.int32) + b) // 2).astype(np.uint8), b]
    plan = plan_span(5, 4)
    r = rife_recon(_keys([0, 100]), plan, avg_engine)
    assert len(r) == 5
    assert r[0][0, 0, 0] == 0 and r[4][0, 0, 0] == 100
    assert r[2][0, 0, 0] == 50                  # first-level midpoint


def test_rife_recon_rejects_non_power_of_two():
    with pytest.raises(ValueError):
        rife_recon(_keys([0, 1]), plan_span(4, 3), lambda a, b: [a, a, b])


def test_reconstruction_rejects_wrong_key_count():
    with pytest.raises(ValueError, match="expected 3 keys"):
        hold_copy_recon(_keys([0, 1]), plan_span(5, 2))


def test_fill_mids_rejects_negative_depth():
    with pytest.raises(ValueError, match="non-negative"):
        fill_mids("A", "B", -1, lambda a, b: [a, a, b])
