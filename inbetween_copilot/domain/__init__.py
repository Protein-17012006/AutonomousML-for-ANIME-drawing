"""Shared domain values with no application, adapter, or service dependencies."""

from inbetween_copilot.domain.character import (
    CharacterSpec,
    condition_qa_prompt,
    reference_frames_for_gen,
)
from inbetween_copilot.domain.states import (
    CorrectionStatus,
    PairAction,
    PlanAction,
    QAStatus,
    Route,
)

__all__ = [
    "CharacterSpec",
    "CorrectionStatus",
    "PairAction",
    "PlanAction",
    "QAStatus",
    "Route",
    "condition_qa_prompt",
    "reference_frames_for_gen",
]
