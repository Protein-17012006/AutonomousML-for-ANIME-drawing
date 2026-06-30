"""U2 -- the perturbation harness. Produces K small-noise views of a clip with a
deterministic numpy-only battery (resize, shift, temporal jitter), then measures
each channel's verdict-flip rate across the views. A channel whose verdict flips
under tiny perturbation is exactly where gaming lives -> this is both the
robustness measurement and the stability input to the confidence aggregator."""
from __future__ import annotations

import numpy as np


def _resize_down(frames, i):
    a = np.asarray(frames)
    return a[..., ::2, ::2, :]                       # nearest-neighbour shrink


def _shift(frames, i):
    a = np.asarray(frames)
    return np.roll(a, shift=1 + (i % 2), axis=-2)    # horizontal pixel shift


def _temporal_jitter(frames, i):
    a = np.asarray(frames)
    if a.shape[0] < 2:
        return a
    return np.roll(a, shift=1, axis=0)               # advance the frame index by 1


def _identity(frames, i):
    return np.asarray(frames)


def default_transforms():
    return [_resize_down, _shift, _temporal_jitter, _identity]


def perturb_views(frames, k: int = 4, *, transforms=None) -> list:
    transforms = transforms if transforms is not None else default_transforms()
    return [t(frames, i) for i, t in enumerate(transforms[:k])]


def flip_rates(frames, views, *, channel_fns) -> dict:
    out = {}
    for name, fn in channel_fns.items():
        if not views:
            out[name] = 1.0
            continue
        try:
            base = bool(fn(frames)[1])
        except Exception:
            out[name] = 1.0
            continue
        flips = 0
        for v in views:
            try:
                if bool(fn(v)[1]) != base:
                    flips += 1
            except Exception:
                flips += 1
        out[name] = flips / len(views)
    return out
