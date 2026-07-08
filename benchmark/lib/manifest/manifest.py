"""Suite manifest — the frozen ground truth of the planted-deviation benchmark.

Freeze discipline (ADR-0010): once a manifest on disk says frozen=true it can
never be overwritten by code. Results are only comparable against a frozen
suite; rebuilding after freezing would invalidate every recorded number.
"""
from __future__ import annotations

from dataclasses import dataclass, field

# FrozenManifestError moved to frozen.py (P4 2026-07-08); re-exported here so
# every existing `from benchmark.lib.manifest.manifest import FrozenManifestError`
# keeps working.
from benchmark.lib.manifest.frozen import (FrozenManifestError,  # noqa: F401
                                           load_dataclass_manifest,
                                           save_dataclass_manifest)


@dataclass
class Manifest:
    version: str
    source_dir: str
    spec_path: str
    cuts: list[dict] = field(default_factory=list)
    plants: list[dict] = field(default_factory=list)
    trap: dict = field(default_factory=dict)
    frozen: bool = False


def save_manifest(manifest: Manifest, path: str) -> str:
    return save_dataclass_manifest(manifest, path, kind="manifest")


def load_manifest(path: str) -> Manifest:
    return load_dataclass_manifest(Manifest, path, kind="manifest")
