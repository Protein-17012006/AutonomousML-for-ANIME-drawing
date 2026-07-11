"""Typed values produced by wide-gap triage."""
from __future__ import annotations

from dataclasses import asdict, dataclass
from enum import Enum


class GapClass(str, Enum):
    __str__ = str.__str__
    SCENE_CUT = "scene_cut"
    CAMERA_MOVE = "camera_move"
    POSE_SNAP = "pose_snap"
    LARGE_ACTION = "large_action"


class TriageConfidence(str, Enum):
    __str__ = str.__str__
    HIGH = "high"
    MEDIUM = "medium"


@dataclass(frozen=True)
class GapTriage:
    cls: GapClass
    keys_suggested: int
    confidence: TriageConfidence
    evidence: dict

    def __post_init__(self) -> None:
        object.__setattr__(self, "cls", GapClass(self.cls))
        object.__setattr__(self, "confidence", TriageConfidence(self.confidence))


@dataclass(frozen=True)
class TriageResult:
    diagnosis: GapTriage
    brief: str

    def to_payload(self) -> dict:
        return {**asdict(self.diagnosis), "brief": self.brief}
