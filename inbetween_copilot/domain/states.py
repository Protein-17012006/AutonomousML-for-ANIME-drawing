"""Stable state vocabulary shared by the co-pilot use cases.

This module deliberately depends only on the Python standard library.  Feature
packages may share these values without importing the pipeline orchestrator.
"""
from __future__ import annotations

from enum import Enum


class PairAction(str, Enum):
    """What the co-pilot did with a key-pair."""

    __str__ = str.__str__
    FILLED = "filled"
    GENERATED = "generated"
    NEEDS_KEY = "needs_key"


class PlanAction(str, Enum):
    """Whether a pair may be filled or needs another key."""

    __str__ = str.__str__
    FILL = "fill"
    NEEDS_KEY = "needs_key"


class QAStatus(str, Enum):
    """Three-state self-QA outcome."""

    __str__ = str.__str__
    PASS = "pass"
    ABSTAIN = "abstain"
    FLAG = "flag"


class Route(str, Enum):
    """Engine/policy used to fill a pair."""

    __str__ = str.__str__
    HOLD = "hold"
    RIFE = "rife"
    SNAP_PRESERVE = "snap_preserve"
    GENERATIVE = "generative"


class CorrectionStatus(str, Enum):
    """How the bounded correction loop ended."""

    __str__ = str.__str__
    RESOLVED = "resolved"
    NEEDS_KEY = "needs_key"
    UNRESOLVED = "unresolved"
