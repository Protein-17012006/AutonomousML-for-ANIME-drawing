"""Ports used by the wide-gap triage application service."""
from __future__ import annotations

from typing import Protocol

from inbetween_copilot.triage.models import GapTriage


class BriefWriter(Protocol):
    def __call__(self, triage: GapTriage) -> str: ...
