"""Generic frozen-manifest persistence (P4, architecture review 2026-07-08).

The freeze discipline (ADR-0010) — a frozen=true manifest on disk can never be
overwritten by code — was implemented twice verbatim (manifest.py / motion
manifest.py) and two more suite types grew ad-hoc shapes. This is the ONE body;
per-type modules keep their public save_*/load_* names and pass `kind` so error
messages stay byte-identical.
"""
from __future__ import annotations

import dataclasses
import json
import os


class FrozenManifestError(RuntimeError):
    """save refused to overwrite a frozen manifest."""


def load_dataclass_manifest(cls, path: str, *, kind: str = "manifest"):
    """Load `cls` from JSON at `path`, ignoring unknown keys (forward-compat)."""
    try:
        with open(path, encoding="utf-8") as f:
            raw = json.load(f)
    except (OSError, json.JSONDecodeError) as e:
        raise RuntimeError(f"cannot load {kind} {path!r}: {e}") from e
    known = {f.name for f in dataclasses.fields(cls)}
    return cls(**{k: v for k, v in raw.items() if k in known})


def save_dataclass_manifest(manifest, path: str, *, kind: str = "manifest") -> str:
    """Write `manifest` as JSON — unless a FROZEN one already sits at `path`."""
    if os.path.exists(path):
        try:
            existing_frozen = load_dataclass_manifest(type(manifest), path, kind=kind).frozen
        except RuntimeError:
            existing_frozen = False  # corrupt manifest: overwriting is fine
        if existing_frozen:
            raise FrozenManifestError(
                f"{kind} at {path!r} is frozen — refusing to overwrite. "
                "A frozen suite is the benchmark's ground truth.")
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(dataclasses.asdict(manifest), f, indent=2)
    return path
