"""Per-pair routing decision: FILL (interpolable) vs NEEDS_KEY (gap too large).

The interpolable gate (validated AUC 0.991) decides, per consecutive artist
key-pair, whether the system may fill the in-betweens or must ask the artist
to draw one more breakdown key. keys_needed names the *minimum* extra keys.
"""
from __future__ import annotations

from inbetween_copilot.domain.states import PlanAction
from inbetween_copilot.pipeline.plan_models import KeyPlan, PairPlan
# Canonical value + full recalibration history live in inbetween_copilot.thresholds.
from inbetween_copilot.thresholds import TAU_GATE


def _default_keys_needed(gap: float, *, tau_gate: float = TAU_GATE) -> int:
    if gap < tau_gate:
        return 0
    if gap < 2 * tau_gate:
        return 1
    return 2


def build_key_plan(gaps: list[float], regimes: list[str], *,
                   tau_gate: float = TAU_GATE,
                   keys_needed_fn=None) -> KeyPlan:
    if len(gaps) != len(regimes):
        raise ValueError(f"gaps ({len(gaps)}) and regimes ({len(regimes)}) length mismatch")
    if keys_needed_fn is None:
        keys_needed_fn = lambda g: _default_keys_needed(g, tau_gate=tau_gate)
    pairs: list[PairPlan] = []
    for i, (g, r) in enumerate(zip(gaps, regimes)):
        if g < tau_gate:
            pairs.append(PairPlan(index=i, gap=g, regime=r, action=PlanAction.FILL, keys_to_request=0))
        else:
            pairs.append(PairPlan(index=i, gap=g, regime=r, action=PlanAction.NEEDS_KEY,
                                  keys_to_request=int(keys_needed_fn(g))))
    total = sum(p.keys_to_request for p in pairs)
    n_fillable = sum(1 for p in pairs if p.action == PlanAction.FILL)
    return KeyPlan(pairs=pairs, total_keys_requested=total, n_fillable=n_fillable)
