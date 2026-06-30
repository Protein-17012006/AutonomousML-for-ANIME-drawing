"""Deterministic signal-based motion-error detectors (hybrid specialist channel).

The VLM motion detector is strong on impossible_morph but blind to flicker_pop
(0/3) — a physics-y, high-frequency phenomenon a cheap signal detector catches
better. `detect_spikes` is the core: given a per-frame scalar series it flags
ISOLATED spikes (a value far off the local trend whose neighbours agree),
distinct from smooth motion. Fed luma/colour per-frame features it becomes a
flicker_pop detector to ensemble with the VLM.
"""
from __future__ import annotations

import os

_FRAME_EXTS = (".png", ".jpg", ".jpeg", ".webp")


def _median(xs: list[float]) -> float:
    s = sorted(xs)
    n = len(s)
    if n == 0:
        return 0.0
    m = n // 2
    return s[m] if n % 2 else 0.5 * (s[m - 1] + s[m])


def detect_spikes(series, *, k: float = 4.0, floor: float = 2.0,
                  w: int = 2) -> list[int]:
    """Indices of ISOLATED spikes in a 1-D per-frame series.

    A spike at frame i = its value sits far off a ROBUST local baseline (the
    median of the ±w window EXCLUDING i, so the spike itself can't drag the
    baseline) relative to the series' own typical adjacent variation. Smooth
    motion tracks its local median (deviation ~0); an isolated pop deviates at
    exactly the spiking frame — the median window keeps its neighbours from also
    firing. `floor` stops near-static clips (median adjacent-diff ~0) from making
    a tiny blip look huge; `k` is the multiple of that scale that counts as a pop.
    """
    n = len(series)
    if n < 3:
        return []
    adj = [abs(series[i + 1] - series[i]) for i in range(n - 1)]
    scale = max(_median(adj), floor)
    out = []
    for i in range(n):
        window = [series[j] for j in range(i - w, i + w + 1)
                  if 0 <= j < n and j != i]
        if len(window) < 2:
            continue
        if abs(series[i] - _median(window)) > k * scale:
            out.append(i)
    return out


def _frame_paths(clip_dir: str) -> list[str]:
    return [os.path.join(clip_dir, n) for n in sorted(os.listdir(clip_dir))
            if n.lower().endswith(_FRAME_EXTS)]


def frame_features(paths: list[str]) -> dict[str, list[float]]:
    """Per-frame mean luma + R/G/B (on a 32x32 thumbnail) — the channels a
    flicker_pop perturbs. Returns {feature_name: [value per frame]}."""
    import numpy as np
    from PIL import Image
    lum, r, g, b = [], [], [], []
    for p in paths:
        a = np.asarray(Image.open(p).convert("RGB").resize((32, 32)),
                       dtype=np.float32)
        rr, gg, bb = (float(a[..., c].mean()) for c in range(3))
        r.append(rr); g.append(gg); b.append(bb)
        lum.append(0.299 * rr + 0.587 * gg + 0.114 * bb)
    return {"luma": lum, "r": r, "g": g, "b": b}


def flicker_verdict(clip_dir: str, **kw) -> dict:
    """Deterministic flicker_pop verdict for one clip: flag a frame that spikes
    in ANY of luma/R/G/B. Returns {has_flicker, flicker_frames}."""
    feats = frame_features(_frame_paths(clip_dir))
    frames: set[int] = set()
    for series in feats.values():
        frames.update(detect_spikes(series, **kw))
    fr = sorted(frames)
    return {"has_flicker": bool(fr), "flicker_frames": fr}
