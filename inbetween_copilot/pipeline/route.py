"""Engine selection for a fillable (gap < tau_gate) key-pair.

Cadence-preserving (the "45fps not 60" principle): a held drawing is COPIED,
a snap KEEPS its timing, only genuine small motion is RIFE-warped. None of
these morph a drawing that should not move.
"""
from __future__ import annotations

from inbetween_copilot.pipeline.states import Route

_ROUTES = {"hold": Route.HOLD, "small": Route.RIFE, "snap": Route.SNAP_PRESERVE}


def choose_route(regime: str) -> Route:
    try:
        return _ROUTES[regime]
    except KeyError:
        raise ValueError(f"unknown regime {regime!r} (expected hold/small/snap)")
