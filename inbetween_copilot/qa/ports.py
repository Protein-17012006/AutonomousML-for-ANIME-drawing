"""Ports implemented by binary and calibrated QA strategies."""
from __future__ import annotations

from typing import Protocol

from inbetween_copilot.qa.models import QAVerdict


class PerceptionPolicy(Protocol):
    def __call__(self, frames) -> QAVerdict: ...
