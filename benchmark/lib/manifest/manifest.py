"""Suite manifest — the frozen ground truth of the planted-deviation benchmark.

Freeze discipline (ADR-0010): once a manifest on disk says frozen=true it can
never be overwritten by code. Results are only comparable against a frozen
suite; rebuilding after freezing would invalidate every recorded number.
"""
from __future__ import annotations

import dataclasses
import json
import os
from dataclasses import dataclass, field


class FrozenManifestError(RuntimeError):
    """save_manifest refused to overwrite a frozen manifest."""


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
    if os.path.exists(path):
        try:
            existing_frozen = load_manifest(path).frozen
        except RuntimeError:
            existing_frozen = False  # corrupt manifest: overwriting is fine
        if existing_frozen:
            raise FrozenManifestError(
                f"manifest at {path!r} is frozen — refusing to overwrite. "
                "A frozen suite is the benchmark's ground truth.")
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(dataclasses.asdict(manifest), f, indent=2)
    return path


def load_manifest(path: str) -> Manifest:
    try:
        with open(path, encoding="utf-8") as f:
            raw = json.load(f)
    except (OSError, json.JSONDecodeError) as e:
        raise RuntimeError(f"cannot load manifest {path!r}: {e}") from e
    known = {f.name for f in dataclasses.fields(Manifest)}
    return Manifest(**{k: v for k, v in raw.items() if k in known})
