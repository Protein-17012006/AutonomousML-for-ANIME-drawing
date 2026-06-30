"""Hold-aware interpolation repair: a softness-triggered, reference-free generation
fix for small-gap on-2s ghosts.

On-2s anime holds a drawing; when an adjacent source pair straddles a held drawing,
RIFE morphs a ghost in the in-between. The true middle is almost always a HELD
drawing (== one endpoint), so the fix is to NOT morph -- copy the held drawing.
A hold is invisible to the even sources alone, but the resulting RIFE ghost is
SOFT, so the softness signal is the deploy trigger (ties to `softness_signal.py`).

Rule, per interpolated position k (middle clip[2k+1] between sources clip[2k],
clip[2k+2]): if `1 - sharpness(mid)/mean(sharpness(sL,sR)) > tau`, replace the
middle with the SHARPER endpoint (hold the crisp drawing); else keep RIFE.
Measured on real on-2s clips (suite_on2s_v3): +3-5.6 dB recon vs RIFE-all.

Honest scope: holds dominate on-2s content, so on a MIXED stream `tau` must stay
conservative (~0.10-0.15) or genuine continuous motion gets wrongly held. Deploy:
gap_gate -> RIFE -> hold_route. Sibling of `softness_signal.py` / `spatial_quality.py`.
"""
from __future__ import annotations

import numpy as np

from benchmark.lib.signals.spatial_quality import frame_sharpness

_EPS = 1e-6


def hold_route(clip, *, tau: float = 0.12, size: int = 256):
    """Repair RIFE on-2s ghosts in a 16-frame 2x clip by holding the sharper
    endpoint at soft (ghosted) interp positions.

    `clip` = ``[s0, m0, s1, m1, ..., s7, m7]`` (arrays or paths). Returns
    ``(new_clip, n_rerouted)``: a copy with soft middles replaced by the sharper
    neighbouring source. Only positions with both sources present (k = 0..6) are
    considered; the trailing middle is left as-is.
    """
    out = list(clip)
    n = 0
    for k in range(7):                       # k=7's right source is absent in a 16f clip
        iL, iM, iR = 2 * k, 2 * k + 1, 2 * k + 2
        shL = frame_sharpness(clip[iL], size=size)
        shR = frame_sharpness(clip[iR], size=size)
        ref = (shL + shR) / 2
        if ref < _EPS:
            continue
        soft = 1.0 - frame_sharpness(clip[iM], size=size) / ref
        if soft > tau:
            out[iM] = clip[iL] if shL >= shR else clip[iR]   # hold the sharper drawing
            n += 1
    return out, n
