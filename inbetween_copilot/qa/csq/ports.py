"""Persistence port for fitted CSQ artifacts."""
from __future__ import annotations

from typing import Protocol

from inbetween_copilot.qa.csq.models import CSQArtifact


class CSQArtifactStore(Protocol):
    def load(self, path: str) -> CSQArtifact: ...
    def save(self, artifact: CSQArtifact, path: str) -> None: ...
