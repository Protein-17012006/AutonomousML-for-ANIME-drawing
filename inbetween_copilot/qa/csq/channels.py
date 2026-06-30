"""U1 -- the channel bank. Runs the injected, independent QA signal functions and
normalizes each to a comparable ChannelScore. A channel that errors is dropped
(degrade toward fewer channels -> higher uncertainty downstream), never raises."""
from __future__ import annotations

from inbetween_copilot.qa.csq.verdict import ChannelScore


def _clip01(x: float) -> float:
    return 0.0 if x < 0.0 else 1.0 if x > 1.0 else x


def channel_scores(frames, *, channel_fns) -> dict:
    out = {}
    for name, fn in channel_fns.items():
        try:
            score, fires = fn(frames)
        except Exception:
            continue
        out[name] = ChannelScore(name, _clip01(float(score)), bool(fires))
    return out
