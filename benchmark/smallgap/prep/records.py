# benchmark/smallgap/records.py
"""Build MotionManifest-compatible clip records for suite_smallgap and freeze.

A clip carries the required motion-manifest keys plus the small-gap extras
(regime/gen/objective/split_group). build_motion_manifest validates the
required subset; extra dict keys pass through to disk unchanged.
"""
from __future__ import annotations

from benchmark.lib.manifest.motion_manifest import (build_motion_manifest,
                                        save_motion_manifest)


def clip_record(cid: str, *, frame_count: int, regime: str, gen: str,
                role: str, teacher_votes: list, objective: dict,
                split_group: str, has_true_middle: bool = True,
                error_type: str = "", error_frames: list | None = None,
                explanation: str = "") -> dict:
    if regime not in ("hold", "small", "snap"):
        raise ValueError(f"bad regime {regime!r}")
    if gen not in ("rife", "blend"):
        raise ValueError(f"bad gen {gen!r}")
    if role not in ("clean", "error"):
        raise ValueError(f"bad role {role!r}")
    for k in ("psnr", "ssim"):  # lpips is attached operationally -> may be None
        if k not in objective:
            raise ValueError(f"objective missing required key {k!r}")
    return {
        "id": cid, "frame_count": frame_count, "role": role,
        "teacher_votes": list(teacher_votes), "error_type": error_type,
        "error_frames": list(error_frames) if error_frames else [],
        "explanation": explanation,
        "regime": regime, "gen": gen,
        "psnr": objective.get("psnr"), "ssim": objective.get("ssim"),
        "lpips": objective.get("lpips"),
        "has_true_middle": has_true_middle, "split_group": split_group,
    }


def freeze_suite(clips: list[dict], path: str, *, source: str) -> str:
    m = build_motion_manifest(clips, source=source, generator="rife+blend",
                              version="smallgap-v1")
    m.frozen = True
    return save_motion_manifest(m, path)
