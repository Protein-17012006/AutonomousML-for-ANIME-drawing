"""Hold-aware frame scoring.

On-2s/3s anime repeats frames (measured 31.8-61.3% across shows): an engine
that just copies key A gets a free perfect score on those GT frames. The
hold-aware numbers EXCLUDE GT frames that duplicate their predecessor
(gap_score < eps, same eps=0.005 as suite_widegap keys_true derivation); raw
numbers are kept alongside for reference. PSNR of identical frames is
capped at 60 dB (inf guard).
"""
from __future__ import annotations

import numpy as np
from skimage.metrics import peak_signal_noise_ratio, structural_similarity

from benchmark.lib.signals.motion_primitives import gap_score

DUP_EPS = 0.005
PSNR_CAP = 60.0


def dup_mask(gt: list[np.ndarray], eps: float = DUP_EPS) -> list[bool]:
    return [False] + [gap_score(gt[i - 1], gt[i]) < eps for i in range(1, len(gt))]


def score_frames(gt: list[np.ndarray], recon: list[np.ndarray],
                 mid_idx: list[int], dup: list[bool]) -> list[dict]:
    if len(gt) != len(recon) or len(dup) != len(gt):
        raise ValueError(
            f"score length mismatch: gt={len(gt)} recon={len(recon)} dup={len(dup)}")
    rows = []
    for i in mid_idx:
        if i < 0 or i >= len(gt):
            raise ValueError(f"mid frame index out of range: {i}")
        if np.array_equal(gt[i], recon[i]):
            p, s = PSNR_CAP, 1.0
        else:
            p = peak_signal_noise_ratio(gt[i], recon[i], data_range=255)
            p = PSNR_CAP if not np.isfinite(p) else min(float(p), PSNR_CAP)
            s = float(structural_similarity(gt[i], recon[i], channel_axis=2,
                                            data_range=255))
        rows.append({"idx": i, "psnr": p, "ssim": s, "held": dup[i]})
    return rows


def aggregate(rows: list[dict]) -> dict:
    live = [r for r in rows if not r["held"]]
    def _m(rs, k):
        return float(np.mean([r[k] for r in rs])) if rs else None
    return {
        "psnr_hold": _m(live, "psnr"), "ssim_hold": _m(live, "ssim"),
        "psnr_raw": _m(rows, "psnr"), "ssim_raw": _m(rows, "ssim"),
        "n_scored": len(live), "n_held": len(rows) - len(live),
    }


def win_rate(per_clip_a: list[dict], per_clip_b: list[dict]) -> float:
    """Fraction of comparable clips where a beats b on psnr_hold.

    Clips whose psnr_hold is None on either side (all-held: zero live mids)
    are excluded from the denominator; no comparable clips -> nan.
    """
    pairs = [(a, b) for a, b in zip(per_clip_a, per_clip_b)
             if a["psnr_hold"] is not None and b["psnr_hold"] is not None]
    if not pairs:
        return float("nan")
    wins = sum(1 for a, b in pairs if a["psnr_hold"] > b["psnr_hold"])
    return wins / len(pairs)
