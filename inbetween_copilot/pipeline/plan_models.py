"""Typed planning values, separated from the planning policy."""
from __future__ import annotations

from dataclasses import dataclass

from inbetween_copilot.domain.states import PlanAction


@dataclass(frozen=True)
class PairPlan:
    index: int
    gap: float
    regime: str
    action: PlanAction
    keys_to_request: int
    # The threshold this pair's gap was compared against. Carried HERE rather
    # than passed to the triage factory so it cannot drift from the tau the
    # session actually ran, and so gap can never be rendered without it — gap
    # alone is not a reason. Defaulted and LAST: PairPlan is constructed
    # positionally in plan.py and in tests.
    tau_gate: float | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "action", PlanAction(self.action))


@dataclass
class KeyPlan:
    pairs: list[PairPlan]
    total_keys_requested: int
    n_fillable: int
