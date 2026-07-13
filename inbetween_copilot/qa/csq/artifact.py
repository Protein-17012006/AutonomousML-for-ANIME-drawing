"""Compatibility facade for the JSON-backed CSQ artifact adapter."""
from __future__ import annotations

from inbetween_copilot.qa.csq.models import CSQArtifact


def save_artifact(artifact: CSQArtifact, path: str) -> None:
    from inbetween_copilot.infrastructure.artifact_json import CSQArtifactJsonStore
    CSQArtifactJsonStore().save(artifact, path)


def load_artifact(path: str) -> CSQArtifact:
    from inbetween_copilot.infrastructure.artifact_json import CSQArtifactJsonStore
    return CSQArtifactJsonStore().load(path)


__all__ = ["CSQArtifact", "load_artifact", "save_artifact"]
