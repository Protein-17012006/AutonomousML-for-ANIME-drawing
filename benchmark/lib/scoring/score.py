"""Score one arm's findings against the frozen manifest.

Rules (locked in the plan — do not change without an ADR note):
- only non-info findings count;
- a plant is caught by a finding on its exact frame whose class is in
  accept_classes; credit goes to accept_classes[0];
- non-info findings on non-planted frames of clean/planted cuts are false
  positives for their class;
- extra classes on a PLANTED frame are not penalized (the plant physically
  changed pixels; cross-class echoes are expected);
- any non-info finding in a trap cut is a trap alarm.
"""
from __future__ import annotations

from benchmark.lib.manifest.manifest import Manifest

_CLASSES = ("palette", "palette_drift", "costume_detail")


def _is_real(f: dict) -> bool:
    return (f.get("deviation_class") not in (None, "info")
            and f.get("severity") != "info")


def score_arm(findings_by_cut: dict[str, list[dict]],
              manifest: Manifest) -> dict:
    roles = {c["name"]: c["role"] for c in manifest.cuts}
    per_class = {c: {"caught": 0, "missed": 0, "false": 0} for c in _CLASSES}
    planted_frames = {(p["cut"], p["frame"]) for p in manifest.plants}

    for p in manifest.plants:
        hits = [f for f in findings_by_cut.get(p["cut"], [])
                if _is_real(f) and f.get("frame") == p["frame"]
                and f.get("deviation_class") in p["accept_classes"]]
        primary = p["accept_classes"][0]
        per_class[primary]["caught" if hits else "missed"] += 1

    trap_alarms = 0
    for cut, findings in findings_by_cut.items():
        role = roles.get(cut, "clean")
        for f in findings:
            if not _is_real(f):
                continue
            if role == "trap":
                trap_alarms += 1
                continue
            if (cut, f.get("frame")) in planted_frames:
                continue
            cls = f.get("deviation_class")
            if cls in per_class:
                per_class[cls]["false"] += 1

    return {"per_class": per_class, "trap_alarms": trap_alarms,
            "n_plants": len(manifest.plants)}
