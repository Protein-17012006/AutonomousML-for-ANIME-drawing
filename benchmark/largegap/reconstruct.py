"""Reconstruction engines that share one contract: keys + SpanPlan -> full
dense frame list (n_used long, keys at key_idx verbatim).

hold/blend are the honesty baselines from the standing eval advice (naive
blend BEAT both LDF and RIFE in the 06-22 small-gap probe — omitting it
fakes the numbers). rife_recon recursively bisects each gap with a pairwise
mid engine (service contract: engine(a, b) -> [a, mid, b]).
"""
from __future__ import annotations

import numpy as np

from benchmark.largegap.span import SpanPlan


def _validate_keys(keys: list[np.ndarray], plan: SpanPlan) -> None:
    if len(keys) != len(plan.key_idx):
        raise ValueError(
            f"expected {len(plan.key_idx)} keys for span, got {len(keys)}")


def hold_copy_recon(keys: list[np.ndarray], plan: SpanPlan) -> list[np.ndarray]:
    _validate_keys(keys, plan)
    tsf = plan.key_idx[1] - plan.key_idx[0]
    return [keys[i // tsf] for i in range(plan.n_used)]


def blend_recon(keys: list[np.ndarray], plan: SpanPlan) -> list[np.ndarray]:
    _validate_keys(keys, plan)
    tsf = plan.key_idx[1] - plan.key_idx[0]
    out = []
    for i in range(plan.n_used):
        j, r = divmod(i, tsf)
        if r == 0:
            out.append(keys[j])
            continue
        t = r / tsf
        a, b = keys[j].astype(np.float32), keys[j + 1].astype(np.float32)
        out.append(np.clip((1 - t) * a + t * b, 0, 255).round().astype(np.uint8))
    return out


def fill_mids(a, b, depth: int, engine) -> list:
    """The 2**depth - 1 in-between frames of one gap, recursive bisection."""
    if depth < 0:
        raise ValueError(f"depth must be non-negative, got {depth}")
    if depth == 0:
        return []
    mid = engine(a, b)[1]
    return fill_mids(a, mid, depth - 1, engine) + [mid] + fill_mids(mid, b, depth - 1, engine)


def rife_recon(keys: list[np.ndarray], plan: SpanPlan,
               engine) -> list[np.ndarray]:
    _validate_keys(keys, plan)
    tsf = plan.key_idx[1] - plan.key_idx[0]
    depth = tsf.bit_length() - 1
    if 2 ** depth != tsf:
        raise ValueError(f"recursive bisection needs power-of-2 tsf, got {tsf}")
    out: list[np.ndarray] = []
    for a, b in zip(keys, keys[1:]):
        out.append(a)
        out.extend(fill_mids(a, b, depth, engine))
    out.append(keys[-1])
    return out
