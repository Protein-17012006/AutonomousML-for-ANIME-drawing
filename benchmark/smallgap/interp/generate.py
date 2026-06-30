# benchmark/smallgap/generate.py
"""Linear-blend in-between — the guaranteed crossfade-ghost fail anchor.

RIFE generation is the real interpolator and runs on the box (.scratch/smallgap/
gen_rife.py); this numpy blend is the ~0-cost ghost baseline used to guarantee
fail examples even when RIFE is clean on small-gap input.
"""
from __future__ import annotations

import numpy as np


def gen_blend(a: np.ndarray, b: np.ndarray) -> np.ndarray:
    # 0.5*a + 0.5*b stays in [0, 255] for uint8 inputs (no clip needed).
    # np.round is round-half-to-even (banker's): a 0.5 midpoint -> nearest even.
    mid = 0.5 * a.astype(np.float32) + 0.5 * b.astype(np.float32)
    return np.round(mid).astype(np.uint8)
