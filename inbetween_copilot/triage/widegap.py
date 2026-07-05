"""Deterministic wide-gap triage: WHY a pair was gate-refused + key budget.

Numpy-pure (no cv2/torch/network) so it imports and tests anywhere; the caller
(service.engines / benchmark eval) supplies `regime` and `has_cut` computed from
inbetween_copilot.signals. Decision order: scene_cut > camera_move > large_action,
else pose_snap. `regime` is still accepted and recorded in evidence, but since the
2026-07-03 recalibration it is evidence-only, not decision-bearing: tau_snap regimes
were calibrated for consecutive frames and don't transfer to stride-8 wide pairs.
ADR-0015: this DIAGNOSES wide gaps; it never fills them.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np

# Uncalibrated defaults = plan.py's historical buckets scaled to tau_gate. Task 10
# (2026-07-03) attempted to refit these on suite_widegap_v1's 35 non-cut pairs via
# benchmark/widegap/fit_keys_edges.py and STOPPED without shipping: the MAE-minimizing
# fit (0.0188, 0.0278; MAE=0.743 vs default MAE=1.029 on the same 35 pairs) pins e1 to
# the smallest achievable candidate in the search grid -- a degenerate end -- and
# collapses the 3-way split to bucket sizes {1: 1, 2: 6, 3: 28} (~80% of pairs -> "3
# keys"), vs the defaults' balanced {1: 11, 2: 12, 3: 12}. Full-suite keys_within_1
# only rises 0.698 -> 0.717 under the fitted edges, nowhere near the >=0.8 target.
# Root cause: gap_score and keys_true are only weakly/non-monotonically related in
# this suite (consistent with SHIFT_THRESH/ACTION_GAP's finding that gap-based
# signals don't transfer well to stride-8 wide pairs) -- no 2-edge threshold on gap
# alone can meaningfully predict the key budget here. Defaults kept; see
# .superpowers/sdd/task-10-report.md for the full investigation.
KEYS_EDGES: tuple[float, float] = (0.034, 0.068)     # (2*tau, 4*tau) @ tau=0.017

# fitted 2026-07-03 on suite_widegap_v1 (fit_triage_thresholds.py grid; in-sample
# 0.698, LOO 0.660, n=53); the plan's original 0.6-shift + regime-snap tree measured
# 0.472 — tau_snap regimes don't transfer to stride-8 pairs.
SHIFT_THRESH = 0.20
ACTION_GAP = 0.090


def keys_from_gap(gap: float, edges: tuple[float, float] = KEYS_EDGES) -> int:
    if gap < edges[0]:
        return 1
    if gap < edges[1]:
        return 2
    return 3


def global_shift_fraction(a, b) -> float:
    """How much of |b-a| a single global translation explains (0..1).
    Phase-correlation via numpy FFT on the grayscale mean channel."""
    ga = np.asarray(a, float).mean(axis=2)
    gb = np.asarray(b, float).mean(axis=2)
    fa, fb = np.fft.rfft2(ga), np.fft.rfft2(gb)
    cross = fa * np.conj(fb)
    denom = np.abs(cross)
    denom[denom == 0] = 1.0
    corr = np.fft.irfft2(cross / denom, s=ga.shape)
    dy, dx = np.unravel_index(int(np.argmax(corr)), corr.shape)
    if dy > ga.shape[0] // 2:
        dy -= ga.shape[0]
    if dx > ga.shape[1] // 2:
        dx -= ga.shape[1]
    if dy == 0 and dx == 0:
        return 0.0
    shifted = np.roll(np.roll(ga, -dy, axis=0), -dx, axis=1)
    before = float(np.abs(gb - ga).mean())
    after = float(np.abs(gb - shifted).mean())
    if before <= 1e-6:
        return 0.0
    return max(0.0, min(1.0, 1.0 - after / before))


@dataclass(frozen=True)
class GapTriage:
    cls: str            # "scene_cut" | "camera_move" | "pose_snap" | "large_action"
    keys_suggested: int
    confidence: str     # "high" (deterministic separators) | "medium" (default bucket)
    evidence: dict


def classify_gap(a, b, *, gap: float, regime: str, has_cut: bool,
                 tau_gate: float = 0.017) -> GapTriage:
    shift = global_shift_fraction(a, b)
    ev = {"gap": round(float(gap), 4), "shift_frac": round(shift, 3), "regime": regime}
    if has_cut:
        return GapTriage("scene_cut", 0, "high", ev)
    if shift >= SHIFT_THRESH:
        return GapTriage("camera_move", keys_from_gap(gap), "high", ev)
    if gap >= ACTION_GAP:
        return GapTriage("large_action", keys_from_gap(gap), "medium", ev)
    return GapTriage("pose_snap", keys_from_gap(gap), "medium", ev)
