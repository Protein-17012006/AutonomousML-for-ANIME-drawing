"""Callable ports used by the correction application service."""
from __future__ import annotations

from typing import Protocol

from inbetween_copilot.generate.models import CorrectionAction


class Perceiver(Protocol):
    def __call__(self, frames): ...


class Localizer(Protocol):
    def __call__(self, frames): ...


class Director(Protocol):
    def __call__(self, verdict, region, attempts) -> CorrectionAction: ...
