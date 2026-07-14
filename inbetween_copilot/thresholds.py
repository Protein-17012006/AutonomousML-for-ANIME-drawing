"""Calibrated decision thresholds — the single source of truth.

Every default below used to be a literal repeated across pipeline/, qa/,
triage/ and service/ modules, free to drift independently after a
recalibration. Import from here instead of re-typing the number.
"""
from __future__ import annotations

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

# Interp-softness flag threshold: softness above this flags the in-between
# (the validated small-gap OR-fusion channel, recall 0.42->0.78 @ ~0.90 precision).
TAU_SOFT = 0.15

# Window source-motion above this -> reconstruction unverifiable -> abstain.
# Deliberately THE SAME lever as the gate (corr(src_motion, recon_psnr) = -0.81, §5n):
# recalibrating the gate moves the CSQ recall guard with it.
TAU_SRC_MOTION = TAU_GATE
