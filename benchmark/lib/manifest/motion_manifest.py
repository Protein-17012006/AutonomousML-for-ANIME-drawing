"""Motion-suite manifest — frozen ground truth for the ToonCrafter motion benchmark.

Same freeze discipline as benchmark/manifest.py: a frozen=true manifest on disk
can never be overwritten by code. The unit here is a CLIP (not a frame): each
clip is generator output the teacher labeled clean or error.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from benchmark.lib.manifest.frozen import (FrozenManifestError,
                                           load_dataclass_manifest,
                                           save_dataclass_manifest)

__all__ = ["MotionManifest", "FrozenManifestError",
           "save_motion_manifest", "load_motion_manifest",
           "build_motion_manifest"]

_CLIP_KEYS = {"id", "frame_count", "role", "teacher_votes",
              "error_type", "error_frames", "explanation"}


@dataclass
class MotionManifest:
    version: str
    source: str
    generator: str
    clips: list[dict] = field(default_factory=list)
    frozen: bool = False


def save_motion_manifest(manifest: MotionManifest, path: str) -> str:
    return save_dataclass_manifest(manifest, path, kind="motion manifest")


def load_motion_manifest(path: str) -> MotionManifest:
    return load_dataclass_manifest(MotionManifest, path, kind="motion manifest")


def build_motion_manifest(clips: list[dict], *, source: str, generator: str,
                          version: str = "motion-v1") -> MotionManifest:
    """Construct an UNFROZEN MotionManifest from teacher-tallied clip dicts.

    Validates each clip carries the full clip-record schema (the shape
    tally_clip emits) so a malformed operational build fails loudly here
    rather than producing a subtly-wrong frozen suite.
    """
    for c in clips:
        missing = _CLIP_KEYS - set(c)
        if missing:
            raise ValueError(
                f"clip {c.get('id', '?')!r} missing keys: {sorted(missing)}")
    return MotionManifest(version=version, source=source,
                          generator=generator, clips=list(clips), frozen=False)
