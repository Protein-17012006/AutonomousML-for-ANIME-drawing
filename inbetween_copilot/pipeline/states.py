"""Typed states for the co-pilot loop (architecture review 2026-07-08, P2).

These were raw strings compared by convention across pipeline/service. Each enum
subclasses str with the EXACT legacy value, so JSON/SSE payloads, report text and
string comparisons are byte-identical — the enums only make the state machines
visible to the type checker and the reader.

Python 3.10 (no enum.StrEnum): `(str, Enum)` + `__str__ = str.__str__` gives the
3.11 StrEnum behaviour (f-strings render the value, not 'PairAction.FILLED').
"""
from __future__ import annotations

from enum import Enum


class PairAction(str, Enum):
    """PairResult.action — what the co-pilot did with a key-pair."""
    __str__ = str.__str__
    FILLED = "filled"
    GENERATED = "generated"
    NEEDS_KEY = "needs_key"


class PlanAction(str, Enum):
    """PairPlan.action -- whether a pair may be filled or needs another key."""
    __str__ = str.__str__
    FILL = "fill"
    NEEDS_KEY = "needs_key"


class QAStatus(str, Enum):
    """FrameQA.status — the 3-state self-QA outcome (abstain = calibrated path only)."""
    __str__ = str.__str__
    PASS = "pass"
    ABSTAIN = "abstain"
    FLAG = "flag"


class Route(str, Enum):
    """PairResult.route — which engine filled the pair (cadence-preserving set)."""
    __str__ = str.__str__
    HOLD = "hold"
    RIFE = "rife"
    SNAP_PRESERVE = "snap_preserve"
    GENERATIVE = "generative"


class CorrectionStatus(str, Enum):
    """CorrectionResult.status — how the bounded correction loop ended."""
    __str__ = str.__str__
    RESOLVED = "resolved"
    NEEDS_KEY = "needs_key"
    UNRESOLVED = "unresolved"
