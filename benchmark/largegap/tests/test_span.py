import pytest

from benchmark.largegap.span import plan_span


def test_exact_span_65_frames_tsf16():
    p = plan_span(65, 16)
    assert p.n_used == 65
    assert p.key_idx == [0, 16, 32, 48, 64]
    assert len(p.mid_idx) == 60
    assert set(p.key_idx).isdisjoint(p.mid_idx)
    assert sorted(p.key_idx + p.mid_idx) == list(range(65))


def test_trims_partial_tail_gap():
    p = plan_span(70, 16)          # 70 frames -> last full key at 64
    assert p.n_used == 65
    assert p.key_idx[-1] == 64


def test_tsf2():
    p = plan_span(5, 2)
    assert p.key_idx == [0, 2, 4]
    assert p.mid_idx == [1, 3]


def test_too_short_raises():
    with pytest.raises(ValueError):
        plan_span(16, 16)          # no complete gap
