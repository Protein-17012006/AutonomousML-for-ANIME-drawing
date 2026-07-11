"""U5 -- the package builder. Emits low-trust (provenance=agent_montage) labels for
the auto-clean and Claude-confident clips, and a residual/ package (native-res GIF +
CSV) for the clips Claude is unsure on -> the human adjudicates those. Every record
validates against label_schema. The panel is NOT a kappa; the summary says so."""
from __future__ import annotations

import csv
import json
import os

from benchmark.lib.labeling.label_schema import validate


def to_record(clip, role, error_type, *, source, note="", generator="unknown",
              frame_count=16, reference_id="first_last") -> dict:
    return {
        "clip": clip,
        "generator": generator,
        "source_keyframe": "unknown",
        "reference_id": reference_id,
        "frame_count": frame_count,
        "role": role,
        "error_type": error_type if role == "error" else None,
        "artifact": "mild" if role == "error" else "none",
        "is_intentional_stylization": False,
        "stylization_kind": [],
        "error_frames": [],
        "error_bbox": None,
        "explanation": note,
        "provenance": "agent_montage",     # LOW TRUST -- triage, not ground truth
        "source": source,                  # "auto" | "claude"
    }


def write_package(triages, claude_adj, out_dir, *, gif_fn=None, meta=None) -> dict:
    if gif_fn is None:
        from benchmark.triage.gif import build_gif as gif_fn
    meta = meta or {}
    os.makedirs(out_dir, exist_ok=True)
    res_dir = os.path.join(out_dir, "residual")
    os.makedirs(res_dir, exist_ok=True)

    records, residual = [], []
    for t in triages:
        m = meta.get(t.clip, {})
        rec = None
        if t.decision == "auto_clean":
            rec = to_record(t.clip, "clean", None, source="auto",
                            generator=m.get("generator", "unknown"),
                            frame_count=m.get("frame_count", 16))
        else:
            adj = claude_adj.get(t.clip)
            if adj and adj.get("confident"):
                rec = to_record(t.clip, adj["role"], adj.get("error_type"),
                                source="claude", note=adj.get("note", ""),
                                generator=m.get("generator", "unknown"),
                                frame_count=m.get("frame_count", 16))
        if rec is not None and not validate(rec)[0]:
            records.append(rec)
        else:
            residual.append(t)      # not confident, or the record failed schema -> degrade to the human

    with open(os.path.join(out_dir, "triage_labels.json"), "w") as f:
        json.dump({"schema": "label-v1",
                   "provenance_note": "agent_montage = TRIAGE, not ground truth, NOT a kappa",
                   "clips": records}, f, indent=1)

    # residual: native-res GIF per clip + a sheet for the human, ranked most-contested first
    residual.sort(key=lambda t: t.disagreement, reverse=True)
    with open(os.path.join(res_dir, "residual_sheet.csv"), "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["clip", "disagreement", "lens_votes", "role", "error_type", "note"])
        for t in residual:
            votes = ";".join(f"{k}:{v.get('verdict')}" for k, v in t.lens_votes.items())
            w.writerow([t.clip, round(t.disagreement, 3), votes, "", "", ""])
            cdir = meta.get(t.clip, {}).get("clip_dir")
            if cdir:
                gif_fn(cdir, os.path.join(res_dir, f"{t.clip}.gif"), 8)

    counts = {"auto_clean": sum(1 for r in records if r["source"] == "auto"),
              "claude_resolved": sum(1 for r in records if r["source"] == "claude"),
              "residual": len(residual)}
    with open(os.path.join(out_dir, "summary.md"), "w") as f:
        f.write(f"# Triage summary\n\n> agent_montage = TRIAGE, not ground truth, NOT a validity kappa.\n\n"
                f"- auto-clean: {counts['auto_clean']}\n- Claude-resolved: {counts['claude_resolved']}\n"
                f"- residual (for you): {counts['residual']}\n")
    return counts
