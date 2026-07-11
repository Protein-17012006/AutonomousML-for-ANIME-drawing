"""Typed data exchanged by the co-pilot application service."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from inbetween_copilot.pipeline.plan_models import KeyPlan, PairPlan
from inbetween_copilot.pipeline.states import PairAction, Route
from inbetween_copilot.qa.models import FrameQA


@dataclass(frozen=True)
class CopilotCfg:
    tau_gate: float = 0.017
    tau_soft: float = 0.15


@dataclass
class PairResult:
    index: int
    action: PairAction
    route: Route | None
    frames: list | None
    qa: FrameQA | None
    keys_requested: int
    correction: Any = None
    triage: Any = None

    def __post_init__(self) -> None:
        self.action = PairAction(self.action)
        if self.route is not None:
            self.route = Route(self.route)


@dataclass
class CopilotResult:
    pairs: list[PairResult]
    keys_requested_total: int
    flagged: list[int]
    n_autopass: int
    n_corrected: int = 0
    abstained: list[int] = field(default_factory=list)


__all__ = [
    "CopilotCfg", "CopilotResult", "KeyPlan", "PairPlan", "PairResult",
]
