"""Shared motion-suite reader (P4, architecture review 2026-07-08).

Every harness used to hand-roll `load_motion_manifest(os.path.join(suite_dir,
"manifest.json"))` + its own frozen check. One reader, one exception; CLI
runners catch UnfrozenSuiteError, print it and return their usual exit code 2.
(widegap/userstudy suites have different on-disk shapes on purpose — they are
NOT forced through this reader.)
"""
from __future__ import annotations

import os

from benchmark.lib.manifest.motion_manifest import MotionManifest, load_motion_manifest


class UnfrozenSuiteError(RuntimeError):
    """The suite manifest is not frozen — its numbers are not comparable."""


def load_motion_suite(suite_dir: str, *, require_frozen: bool = True) -> MotionManifest:
    manifest = load_motion_manifest(os.path.join(suite_dir, "manifest.json"))
    if require_frozen and not manifest.frozen:
        raise UnfrozenSuiteError(
            f"suite manifest at {suite_dir!r} is not frozen — freeze it first. "
            "Unfrozen numbers are not comparable.")
    return manifest
