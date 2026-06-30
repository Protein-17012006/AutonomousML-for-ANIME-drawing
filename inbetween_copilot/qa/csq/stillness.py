"""Temporal-motion-CONCENTRATION signal — the CSQ anti-Goodhart guard against the
aggressive static-hold attack (§5d #5/§5h). That attack refills (almost) every soft
tile with a hold-copy of the boundary keys, turning a moving clip into a step
function: frozen-A, one hard A->B jump, frozen-B. Its motion is CONCENTRATED in a
single inter-frame gap, unlike a clean clip (motion distributed) or a legit on-2s
hold (≈no motion). `motion_concentration = max(gap) / sum(gap)`, guarded to 0 when
total motion is below `tau_motion` so a GENUINE static hold never fires.

Measured (suite_smallgap + aggressive adversary, 2026-06-24): clean 0/68 fire,
legit holds 0/15, aggressive 34/37 fire at >0.6 — zero false positives on clean,
catches the attack. Reference-free, pure numpy. Used as a deterministic OR-guard
(pass + fires -> flag), NOT a weighted channel, to avoid diluting s on normal errors.
"""
from __future__ import annotations

from inbetween_copilot.signals.motion import gap_score

TAU_MOTION = 0.02      # total inter-frame motion below this = genuine static hold -> 0
TAU_STILL = 0.6        # concentration above this = step-function hold -> fires the guard


TAU_SRC_MOTION = 0.017     # window source-motion above this -> reconstruction unverifiable -> abstain
                           # (= the calibrated tau_gate; corr(src_motion, recon_psnr) = -0.81, §5n)


def window_source_motion(frames) -> float:
    """Mean gap_score over consecutive SOURCE (even-index) frames of a 2x window.
    High = the real frames move a lot -> RIFE reconstruction is unreliable (the QA
    can't verify a high-motion in-between reference-free). 0 if < 2 source frames."""
    src = [frames[i] for i in range(0, len(frames), 2)]
    if len(src) < 2:
        return 0.0
    return float(sum(gap_score(src[i], src[i + 1]) for i in range(len(src) - 1)) / (len(src) - 1))


def motion_concentration(frames, *, tau_motion: float = TAU_MOTION) -> float:
    """max(consecutive gap) / sum(consecutive gaps), in [0,1]; 0 if < 2 frames or
    total motion < tau_motion (a genuine static hold must not fire)."""
    if len(frames) < 2:
        return 0.0
    diffs = [gap_score(frames[i], frames[i + 1]) for i in range(len(frames) - 1)]
    tot = sum(diffs)
    if tot < tau_motion:
        return 0.0
    return float(max(diffs) / tot)
