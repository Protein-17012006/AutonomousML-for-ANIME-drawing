"""Typed outbound ports owned by the co-pilot application workflow.

The pipeline knows callable contracts, not concrete engines or adapters.  The
composition package is the only place that supplies production implementations.
"""
from __future__ import annotations

from dataclasses import dataclass, fields
from typing import Any, Protocol

from inbetween_copilot.domain.states import Route
from inbetween_copilot.pipeline.plan_models import PairPlan
from inbetween_copilot.qa.models import FrameQA

Frame = Any
Frames = list[Frame]


class GapMetric(Protocol):
    def __call__(self, a: Frame, b: Frame) -> float: ...


class RegimeClassifier(Protocol):
    def __call__(self, a: Frame, b: Frame) -> str: ...


class Interpolator(Protocol):
    def __call__(self, route: Route, a: Frame, b: Frame) -> Frames: ...


class BinaryQAEvaluator(Protocol):
    def __call__(self, frames: Frames) -> bool: ...


class SoftnessMetric(Protocol):
    def __call__(self, frames: Frames) -> float: ...


class TriageEvaluator(Protocol):
    def __call__(self, a: Frame, b: Frame, plan: PairPlan) -> "dict | None": ...


class KeyBudget(Protocol):
    def __call__(self, gap: float) -> int: ...


class Generator(Protocol):
    def __call__(self, a: Frame, middle: Frame, b: Frame) -> Frames: ...


class BreakdownSupplier(Protocol):
    def __call__(self, a: Frame, b: Frame) -> "Frame | None": ...


class CorrectionOutcome(Protocol):
    frames: Frames
    status: object


class Corrector(Protocol):
    def __call__(self, frames: Frames, a: Frame, b: Frame) -> CorrectionOutcome: ...


class ThreeStateQAEvaluator(Protocol):
    def __call__(self, frames: Frames) -> FrameQA: ...


@dataclass
class CopilotPorts:
    """Complete engine contract consumed by :class:`RunCopilot`."""

    gap_fn: GapMetric
    regime_fn: RegimeClassifier
    interp_fn: Interpolator
    qa_fn: BinaryQAEvaluator
    softness_fn: SoftnessMetric
    triage_fn: TriageEvaluator
    keys_needed_fn: KeyBudget
    gen_fn: "Generator | None" = None
    breakdown_supply: "BreakdownSupplier | None" = None
    corrector: "Corrector | None" = None
    qa3_fn: "ThreeStateQAEvaluator | None" = None
    qa_window: bool = False

    def __post_init__(self) -> None:
        required = (
            "gap_fn", "regime_fn", "interp_fn", "qa_fn", "softness_fn",
            "triage_fn", "keys_needed_fn",
        )
        optional = ("gen_fn", "breakdown_supply", "corrector", "qa3_fn")
        for name in required:
            if not callable(getattr(self, name)):
                raise TypeError(f"CopilotPorts.{name} must be callable")
        for name in optional:
            value = getattr(self, name)
            if value is not None and not callable(value):
                raise TypeError(f"CopilotPorts.{name} must be callable or None")
        if not isinstance(self.qa_window, bool):
            raise TypeError("CopilotPorts.qa_window must be bool")

    def as_kwargs(self) -> dict:
        """Return exactly the keyword arguments accepted by ``run_copilot``."""

        return {item.name: getattr(self, item.name) for item in fields(CopilotPorts)}
