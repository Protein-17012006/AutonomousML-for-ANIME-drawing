"""Typed values shared by QA policies and pipeline consumers."""
from __future__ import annotations

from dataclasses import dataclass

from inbetween_copilot.pipeline.states import QAStatus


@dataclass(frozen=True)
class FrameQA:
    status: QAStatus
    reason: str
    p_error: "float | None" = None
    u: "float | None" = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "status", QAStatus(self.status))


@dataclass(frozen=True)
class QAVerdict:
    has_error: bool
    err_type: str
    region_hint: str
    explanation: str
    softness: float
    hold_fixable: float = 0.0
    decision: QAStatus = QAStatus.FLAG
    p_error: float = 1.0
    u: float = 0.0

    def __post_init__(self) -> None:
        object.__setattr__(self, "decision", QAStatus(self.decision))
