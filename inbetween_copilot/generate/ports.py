"""Callable contracts used by the bounded correction workflow."""
from __future__ import annotations

from typing import Any, Protocol

from inbetween_copilot.generate.localize import Region
from inbetween_copilot.generate.models import CorrectionAction, CorrectionRound

Frame = Any
Frames = list[Frame]


class Perceive(Protocol):
    def __call__(self, frames: Frames) -> Any: ...


class Localize(Protocol):
    def __call__(self, frames: Frames) -> Region: ...


class Decide(Protocol):
    def __call__(
        self, verdict: Any, region: Region, attempts: list[CorrectionRound],
    ) -> CorrectionAction: ...


class Refill(Protocol):
    def __call__(self, frames: Frames, a: Frame, b: Frame, region: Region) -> Frames: ...


class Escalate(Protocol):
    def __call__(self, a: Frame, b: Frame) -> Frames: ...


class AskKey(Protocol):
    def __call__(self, a: Frame, b: Frame) -> "Frame | None": ...


class SplitFill(Protocol):
    def __call__(self, a: Frame, middle: Frame, b: Frame) -> Frames: ...
