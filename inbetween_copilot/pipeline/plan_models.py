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

    def __post_init__(self) -> None:
        object.__setattr__(self, "action", PlanAction(self.action))


@dataclass
class KeyPlan:
    pairs: list[PairPlan]
    total_keys_requested: int
    n_fillable: int
