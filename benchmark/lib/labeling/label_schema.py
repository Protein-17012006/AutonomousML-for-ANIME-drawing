"""Canonical label-record schema + validator + migrator — ADR-0012 (§3/§5/§7 fields).

One labeled clip = one record with these fields. Beyond the legacy manifest (role/error_type/
error_frames/explanation) this adds the ADR-0012 requirements: `source_keyframe` (§1 split/dedup),
`reference_id` (§5 reference-conditioned), `artifact` severity (visual-integrity axis),
`is_intentional_stylization` + `stylization_kind` (§3 hard-negative tag, NOT a deviation class),
`error_bbox` (§7 spatial grounding, schema-ready though deferred behind the resolution wall), and
`provenance` (§4 label trust — full_res Claude-eyes vs agent_montage).

`validate()` returns (errors, warnings); `migrate_suite()` builds v1 records for suite_identity by
fusing the manifest + the full-res artifact labels + the keyframe-dedup groups. GPU-free.

    python -m benchmark.lib.labeling.label_schema --check <labels.json>        # validate
    python -m benchmark.lib.labeling.label_schema --migrate-suite <out.json>   # build suite_identity v1 records
"""
from __future__ import annotations

import argparse
import json
import os

REQUIRED = ["clip", "generator", "source_keyframe", "reference_id", "frame_count",
            "role", "artifact", "is_intentional_stylization", "error_frames",
            "explanation", "provenance"]
OPTIONAL = ["error_type", "stylization_kind", "error_bbox", "votes"]

ROLES = {"clean", "error"}
ERROR_TYPES = {None, "impossible_morph", "warp_melt", "identity_drift",
               "flicker_pop", "line_art_integrity",
               "bg_coherence", "scene_grounding", "fx_binding"}  # + Phase C (env axis)
ARTIFACTS = {"none", "mild", "strong"}
STYLE_KINDS = {"smear", "impact", "chibi", "banana", "vfx", "aura", "motion_blur"}
PROVENANCE = {"full_res", "hires", "consensus", "error", "agent_montage"}


def validate(rec: dict) -> tuple[list[str], list[str]]:
    errs, warns = [], []
    for f in REQUIRED:
        if f not in rec:
            errs.append(f"missing required field '{f}'")
    if errs:
        return errs, warns
    if rec["role"] not in ROLES:
        errs.append(f"role '{rec['role']}' not in {ROLES}")
    if rec.get("error_type") not in ERROR_TYPES:
        errs.append(f"error_type '{rec.get('error_type')}' invalid")
    if rec["artifact"] not in ARTIFACTS:
        errs.append(f"artifact '{rec['artifact']}' not in {ARTIFACTS}")
    if rec["provenance"] not in PROVENANCE:
        errs.append(f"provenance '{rec['provenance']}' invalid")
    if not isinstance(rec["error_frames"], list):
        errs.append("error_frames must be a list[int]")
    if not isinstance(rec["is_intentional_stylization"], bool):
        errs.append("is_intentional_stylization must be bool")
    # cross-field rules
    if rec["role"] == "error" and not rec.get("error_type"):
        errs.append("role=error requires a non-null error_type")
    if rec["role"] == "clean" and rec.get("error_type"):
        errs.append("role=clean must have error_type=null")
    if rec["is_intentional_stylization"] and not rec.get("stylization_kind"):
        errs.append("is_intentional_stylization=true requires stylization_kind[]")
    for k in rec.get("stylization_kind", []) or []:
        if k not in STYLE_KINDS:
            errs.append(f"stylization_kind '{k}' not in {STYLE_KINDS}")
    # warnings (not hard failures)
    if rec["source_keyframe"] in (None, "", "unknown"):
        warns.append("source_keyframe unknown — split/dedup (§1) cannot be enforced")
    if rec["provenance"] == "agent_montage":
        warns.append("provenance=agent_montage — low trust for severity (§4), needs full-res confirm")
    return errs, warns


def validate_file(path: str) -> int:
    data = json.load(open(path))
    recs = data["clips"] if isinstance(data, dict) and "clips" in data else data
    n_err = n_warn = 0
    for r in recs:
        e, w = validate(r)
        if e:
            n_err += 1
            print(f"  [ERROR] {r.get('clip','?')}: {'; '.join(e)}")
        for msg in w:
            n_warn += 1
            print(f"  [warn]  {r.get('clip','?')}: {msg}")
    print(f"\n{len(recs)} records: {n_err} with errors, {n_warn} warnings.")
    return 1 if n_err else 0


# --- migrator: build suite_identity v1 records from the artifacts we have ---------------------

# Stylization tags from the full-res Claude-eyes review (2026-06-17): deliberate stylizations a
# naive detector might flag — chibi proportions and prominent intended effects. Hard negatives (§3).
_STYLE_TAGS = {
    "id020": ["chibi"], "id046": ["chibi"],
    "id009": ["vfx", "aura"], "id010": ["aura"], "id040": ["vfx"],
    "id042": ["vfx"], "id022": ["vfx"],
}


def migrate_suite(suite_dir: str, artifact_final: str, out: str) -> int:
    man = json.load(open(os.path.join(suite_dir, "manifest.json")))
    gen = man.get("generator", "unknown")
    art = {c["clip"]: c for c in json.load(open(artifact_final))["clips"]}
    # recover source_keyframe groups perceptually (composes with keyframe_dedup)
    from benchmark.lib.signals.keyframe_dedup import find_duplicates
    _, split_group, *_ = find_duplicates(os.path.join(suite_dir, "clips"), thresh=0.93)

    recs = []
    for c in man["clips"]:
        cid = c["id"]
        a = art.get(cid, {})
        raw = a.get("provenance", "agent_montage")
        prov = next((p for p in ("full_res", "hires", "consensus", "error")
                     if raw.startswith(p)), "agent_montage")
        kinds = _STYLE_TAGS.get(cid, [])
        recs.append({
            "clip": cid,
            "generator": gen,
            "source_keyframe": split_group.get(cid, "unknown"),
            "reference_id": "first_last",          # anchor-IVC default (§5)
            "frame_count": c.get("frame_count", 16),
            "role": c.get("role", "clean"),
            "error_type": c.get("error_type"),
            "artifact": a.get("artifact", "none"),
            "is_intentional_stylization": bool(kinds),
            "stylization_kind": kinds,
            "error_frames": c.get("error_frames", []),
            "error_bbox": None,                     # deferred (§7, resolution wall)
            "explanation": c.get("explanation", ""),
            "provenance": prov,
            "votes": a.get("votes", []),
        })
    json.dump({"schema": "label-v1", "suite": suite_dir, "clips": recs},
              open(out, "w"), indent=1)
    n_err = sum(1 for r in recs if validate(r)[0])
    print(f"migrated {len(recs)} records -> {out}  ({n_err} schema errors)")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--check", help="validate a labels JSON against the schema")
    ap.add_argument("--migrate-suite", help="output path; builds suite_identity v1 records")
    ap.add_argument("--suite", default="benchmark/suites/suite_identity")
    ap.add_argument("--artifact-final", default=".scratch/motion_labels/artifact_final.json")
    args = ap.parse_args()
    if args.check:
        return validate_file(args.check)
    if args.migrate_suite:
        return migrate_suite(args.suite, args.artifact_final, args.migrate_suite)
    ap.error("give --check <file> or --migrate-suite <out>")


if __name__ == "__main__":
    raise SystemExit(main())
