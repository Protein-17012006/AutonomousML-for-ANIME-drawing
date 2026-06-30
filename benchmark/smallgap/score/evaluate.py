# benchmark/smallgap/evaluate.py
"""Re-validation analytics: P/R sliced by regime/gen, and the gate AUC.

slice_scores reuses score_motion on per-group sub-manifests. gate_auc measures
whether a deterministic per-window motion score separates snap (not
interpolable) from small+hold (interpolable).
"""
from __future__ import annotations

import dataclasses

from benchmark.lib.manifest.motion_manifest import MotionManifest
from benchmark.lib.scoring.motion_score import score_motion


def _group_key(clip: dict, by: str) -> str:
    if by == "regime+gen":
        return f"{clip['regime']}/{clip['gen']}"
    return str(clip[by])


def slice_scores(verdicts: dict, manifest: MotionManifest,
                 by: str) -> dict[str, dict]:
    groups: dict[str, list[dict]] = {}
    for clip in manifest.clips:
        groups.setdefault(_group_key(clip, by), []).append(clip)
    out: dict[str, dict] = {}
    for key, clips in groups.items():
        sub = dataclasses.replace(manifest, clips=clips)
        out[key] = score_motion(verdicts, sub)
    return out


def gate_auc(window_motions: list[float], is_snap: list[bool]) -> float:
    pos = [m for m, s in zip(window_motions, is_snap) if s]
    neg = [m for m, s in zip(window_motions, is_snap) if not s]
    if not pos or not neg:
        return 0.5
    wins = sum((p > n) + 0.5 * (p == n) for p in pos for n in neg)
    return float(wins / (len(pos) * len(neg)))
