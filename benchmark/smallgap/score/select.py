"""Rank small-regime RIFE clips by objective fidelity vs hidden GT and decide a
GO/NO-GO on whether RIFE small-gap ghosts exist. SSIM is the primary selector
(RIFE small-gap reconstructions should be near-perfect; a clip clearly below the
clean body is a ghost candidate). The GO threshold is a provisional absolute
floor refined by eyeballing the printed percentile distribution."""
from __future__ import annotations

import numpy as np


def select_candidates(objectives, *, ssim_floor: float = 0.95,
                      tail_frac: float = 0.15, n_probe: int = 30) -> dict:
    n = len(objectives)
    if n == 0:
        return {"go": False, "n": 0, "bad": [], "bad_frac": 0.0,
                "candidates": [], "clean_sample": [], "ssim_pcts": {}}
    ranked = sorted(objectives, key=lambda o: o["ssim"])   # worst ssim first
    bad = [o["id"] for o in ranked if o["ssim"] < ssim_floor]
    bad_frac = len(bad) / n
    half = n_probe // 2
    candidates = [o["id"] for o in ranked[:half]]
    clean_sample = [o["id"] for o in ranked[-half:]][::-1]   # best ssim first
    ssims = np.array([o["ssim"] for o in objectives])
    pcts = {f"p{p}": round(float(np.percentile(ssims, p)), 4)
            for p in (5, 10, 25, 50, 90)}
    return {"go": bad_frac >= tail_frac, "n": n, "bad": bad,
            "bad_frac": round(bad_frac, 4), "candidates": candidates,
            "clean_sample": clean_sample, "ssim_pcts": pcts}
