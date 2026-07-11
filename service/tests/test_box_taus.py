from inbetween_copilot.signals.regime import classify
from service.infrastructure.engines import BOX_TAU_HOLD, BOX_TAU_SNAP


def test_box_tau_snap_is_tightened():
    assert BOX_TAU_SNAP == 0.18
    assert BOX_TAU_HOLD == 0.01


def test_classify_boundary_at_production_taus():
    # w0010-like hard motion (0.19) -> snap (copy, no RIFE); clean small (0.15) -> small
    assert classify([0.19], tau_hold=BOX_TAU_HOLD, tau_snap=BOX_TAU_SNAP) == "snap"
    assert classify([0.15], tau_hold=BOX_TAU_HOLD, tau_snap=BOX_TAU_SNAP) == "small"
