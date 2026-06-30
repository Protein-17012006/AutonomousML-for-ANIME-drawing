"""Per-pair routing decision: FILL (interpolable) vs NEEDS_KEY (gap too large).

The interpolable gate (validated AUC 0.991) decides, per consecutive artist
key-pair, whether the system may fill the in-betweens or must ask the artist
to draw one more breakdown key. keys_needed names the *minimum* extra keys.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class PairPlan:
    index: int
    gap: float
    regime: str
    action: str          # "fill" | "needs_key"
    keys_to_request: int


@dataclass
class KeyPlan:
    pairs: list[PairPlan]
    total_keys_requested: int
    n_fillable: int


# Interpolable-gate threshold on gap_score: gap < TAU_GATE -> RIFE can interpolate;
# gap >= TAU_GATE -> ask the artist for a key (RIFE would ghost).
# RECALIBRATED 2026-06-22 (0.18 -> 0.017). A per-pair (gap_score, RIFE-mid-PSNR) study
# across 3 shows (E11 action / silent-witch on-2s / JJK high-motion; "ghost" = RIFE-PSNR
# < 30 dB) found gap_score predicts ghosting at AUC 0.89-0.95, but the old default 0.18
# caught only ~1% of ghosts -> shipped 32-48% RIFE-ghosts mislabelled "interpolable".
# Best per-regime tau was 0.010-0.025 (near-global, spread 0.015); 0.017 gives ghost-recall
# 0.86-0.94 at spec ~0.78 (reject-rate ~half = the genuinely-hard pairs).
# The exact value tracks the quality bar (30 dB) and the acceptable reject-rate -> tune
# per deployment; pass an explicit tau_gate to override. (Drivers: .scratch/copilot/
# {stress_perpair,analyze_gate_calib}.py)
TAU_GATE = 0.017


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
            pairs.append(PairPlan(index=i, gap=g, regime=r, action="fill", keys_to_request=0))
        else:
            pairs.append(PairPlan(index=i, gap=g, regime=r, action="needs_key",
                                  keys_to_request=int(keys_needed_fn(g))))
    total = sum(p.keys_to_request for p in pairs)
    n_fillable = sum(1 for p in pairs if p.action == "fill")
    return KeyPlan(pairs=pairs, total_keys_requested=total, n_fillable=n_fillable)
