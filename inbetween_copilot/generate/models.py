"""Typed actions and results for the bounded correction workflow."""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any

from inbetween_copilot.pipeline.states import CorrectionStatus


class CorrectionActionKind(str, Enum):
    __str__ = str.__str__
    REGION_REFILL = "region_refill"
    ESCALATE_ENGINE = "escalate_engine"
    ASK_KEY = "ask_key"


class CorrectionMethod(str, Enum):
    __str__ = str.__str__
    NONE = ""
    HOLD_COPY = "hold_copy"
    ALT_ENGINE = "alt_engine"


@dataclass(frozen=True)
class CorrectionAction:
    kind: CorrectionActionKind
    region: Any
    method: CorrectionMethod
    reason: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "kind", CorrectionActionKind(self.kind))
        object.__setattr__(self, "method", CorrectionMethod(self.method))


@dataclass
class CorrectionRound:
    action_kind: CorrectionActionKind
    region: Any
    verdict: Any
    u_delta: float = 0.0
    reason: str = ""

    def __post_init__(self) -> None:
        self.action_kind = CorrectionActionKind(self.action_kind)


@dataclass
class CorrectionResult:
    status: CorrectionStatus
    frames: list
    rounds: list[CorrectionRound]
    keys_used: int
    final_verdict: Any

    def __post_init__(self) -> None:
        self.status = CorrectionStatus(self.status)
