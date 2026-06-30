"""Engine selection for a fillable (gap < tau_gate) key-pair.

Cadence-preserving (the "45fps not 60" principle): a held drawing is COPIED,
a snap KEEPS its timing, only genuine small motion is RIFE-warped. None of
these morph a drawing that should not move.
"""
from __future__ import annotations

_ROUTES = {"hold": "hold", "small": "rife", "snap": "snap_preserve"}


def choose_route(regime: str) -> str:
    try:
        return _ROUTES[regime]
    except KeyError:
        raise ValueError(f"unknown regime {regime!r} (expected hold/small/snap)")
