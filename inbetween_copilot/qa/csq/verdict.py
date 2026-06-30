"""Shared CSQ types: the 3-state Decision, a normalized channel score, and the
calibrated verdict the decider emits."""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class Decision(str, Enum):
    PASS = "pass"
    ABSTAIN = "abstain"
    FLAG = "flag"


@dataclass(frozen=True)
class ChannelScore:
    name: str
    score: float    # normalized error-ness in [0, 1]
    fires: bool


@dataclass(frozen=True)
class CSQVerdict:
    decision: Decision
    p_error: float
    s: float
    u: float
    reasons: tuple = ()

    @property
    def confidence(self) -> float:
        return 1.0 - self.u
