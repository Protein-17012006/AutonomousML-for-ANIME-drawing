# benchmark/smallgap/objective.py
"""Objective interpolation-quality metrics vs the held-out GT frame.

PSNR is VALID here because RIFE/blend warp/copy real pixels (unlike a
re-rendering diffusion generator). LPIPS is attached operationally in the
suite-build step (needs a torch model) and is not computed here.
"""
from __future__ import annotations

import numpy as np
from skimage.metrics import structural_similarity

# Cap for identical (inf) frames so a perfect frame still contributes a finite
# value to the per-clip mean rather than being dropped (which would understate
# quality). 100 dB is standard practice for 8-bit VFI reconstruction metrics.
PSNR_MAX = 100.0


def psnr(pred: np.ndarray, gt: np.ndarray) -> float:
    mse = np.mean((pred.astype(np.float64) - gt.astype(np.float64)) ** 2)
    if mse == 0:
        return float("inf")
    return float(20.0 * np.log10(255.0 / np.sqrt(mse)))


def ssim(pred: np.ndarray, gt: np.ndarray) -> float:
    # SSIM is symmetric; pass args in the function's own (pred, gt) order.
    return float(structural_similarity(pred, gt, channel_axis=2,
                                       data_range=255))


def clip_objective(pred_frames: list[np.ndarray],
                   gt_frames: list[np.ndarray]) -> dict:
    if len(pred_frames) != len(gt_frames) or not pred_frames:
        raise ValueError("clip_objective: pred/gt length mismatch or empty")
    # cap inf (identical frame) at PSNR_MAX so perfect frames count toward the
    # mean consistently with how ssim averages every frame.
    psnrs = [min(psnr(p, g), PSNR_MAX) for p, g in zip(pred_frames, gt_frames)]
    ssims = [ssim(p, g) for p, g in zip(pred_frames, gt_frames)]
    return {"psnr": float(np.mean(psnrs)),
            "ssim": float(np.mean(ssims)), "n": len(pred_frames)}
