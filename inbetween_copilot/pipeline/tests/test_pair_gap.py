"""A pair's gap is the number that decided it — and until 2026-08-03 an ACCEPTED
pair threw it away, so "why was pair 1 refused when pair 5 looks worse?" had no
source to answer from."""
import numpy as np

from inbetween_copilot.pipeline.copilot import run_copilot
from inbetween_copilot.pipeline.models import CopilotCfg


def _keys():
    a = np.zeros((8, 8, 3), np.uint8)
    return [a, a + 1, a + 200]


def _run():
    return run_copilot(
        _keys(),
        gap_fn=lambda x, y: float(
            np.abs(x.astype(np.int32) - y.astype(np.int32)).mean() / 100.0),
        regime_fn=lambda x, y: "small",
        interp_fn=lambda route, x, y: [x, x, y],
        qa_fn=lambda frames: False,
        softness_fn=lambda frames: 0.0,
        cfg=CopilotCfg(tau_gate=0.017),
    )


def test_filled_pair_records_the_gap_that_let_it_through():
    pair = _run().pairs[0]
    assert str(pair.action) == "filled"
    assert pair.gap == 0.01


def test_refused_pair_records_the_gap_that_refused_it():
    pair = _run().pairs[1]
    assert str(pair.action) == "needs_key"
    assert pair.gap is not None and pair.gap >= 0.017
