"""Inter-annotator agreement (Cohen's / Fleiss' kappa) — ADR-0012 §4 label-quality gate.

Give >=2 label files; 2 raters -> Cohen's kappa, >=3 -> Fleiss'. Reports raw exact-agreement,
kappa on the FULL category set AND on a binary collapse (present vs none), the 2-rater confusion
matrix, and PASS/FAIL against the ADR-0012 threshold (kappa >= 0.6 on the binary axis). Pure
stdlib so it runs anywhere, with or without the GPU box.

    python -m benchmark.lib.labeling.label_agreement \\
        --labels .scratch/motion_labels/artifact_labels_draft42.json \\
                 .scratch/motion_labels/artifact_vote2.json \\
        --field artifact --present mild,strong --threshold 0.6
"""
from __future__ import annotations

import argparse
import json
import os
from collections import Counter


def load_labels(path: str, field: str) -> dict[str, str]:
    """clip-id -> label string, from {"clips":[{clip, <field>}]} or a bare list."""
    data = json.load(open(path))
    rows = data["clips"] if isinstance(data, dict) and "clips" in data else data
    out = {}
    for r in rows:
        cid = r.get("clip") or r.get("id")
        if cid is None or field not in r:
            continue
        out[cid] = str(r[field])
    return out


def _interpret(kappa: float) -> str:
    # Landis & Koch bands
    for lo, name in [(0.81, "almost perfect"), (0.61, "substantial"),
                     (0.41, "moderate"), (0.21, "fair"), (0.0, "slight"),
                     (-1.0, "poor/negative")]:
        if kappa >= lo:
            return name
    return "?"


def cohen_kappa(a: list[str], b: list[str], cats: list[str]):
    n = len(a)
    po = sum(1 for x, y in zip(a, b) if x == y) / n
    ca, cb = Counter(a), Counter(b)
    pe = sum((ca[c] / n) * (cb[c] / n) for c in cats)
    kappa = 1.0 if pe == 1 else (po - pe) / (1 - pe)
    return po, pe, kappa


def fleiss_kappa(per_item_counts: list[Counter], cats: list[str], n_raters: int):
    N = len(per_item_counts)
    p_j = {c: sum(it.get(c, 0) for it in per_item_counts) / (N * n_raters) for c in cats}
    pe = sum(v * v for v in p_j.values())
    pis = [(sum(it.get(c, 0) ** 2 for c in cats) - n_raters) / (n_raters * (n_raters - 1))
           for it in per_item_counts]
    pbar = sum(pis) / N
    kappa = 1.0 if pe == 1 else (pbar - pe) / (1 - pe)
    return pbar, pe, kappa


def _confusion(a: list[str], b: list[str], cats: list[str], names: tuple[str, str]):
    idx = {c: i for i, c in enumerate(cats)}
    m = [[0] * len(cats) for _ in cats]
    for x, y in zip(a, b):
        m[idx[x]][idx[y]] += 1
    w = max(len(c) for c in cats + list(names)) + 1
    print(f"  confusion (rows={names[0]}, cols={names[1]}):")
    print("    " + "".join(f"{c:>{w}}" for c in [""] + cats))
    for c in cats:
        print("    " + f"{c:>{w}}" + "".join(f"{m[idx[c]][idx[k]]:>{w}}" for k in cats))


def run(paths: list[str], field: str, present: set[str], threshold: float) -> int:
    raters = [(os.path.basename(p), load_labels(p, field)) for p in paths]
    common = set.intersection(*[set(d.keys()) for _, d in raters])
    clips = sorted(common)
    if not clips:
        print("[ERROR] no clips in common across label files"); return 1
    print(f"raters: {[n for n, _ in raters]}")
    print(f"clips compared: {len(clips)} (intersection)\n")

    full_cats = sorted({d[c] for _, d in raters for c in clips})
    bin_of = {c: ("present" if d[c] in present else "none")
              for name, d in raters for c in clips}  # placeholder; rebuilt per rater below

    def col(d, collapse):
        return [("present" if d[c] in present else "none") if collapse else d[c]
                for c in clips]

    for label, cats, collapse in [("FULL categories", full_cats, False),
                                  ("BINARY (present vs none)", ["none", "present"], True)]:
        cols = [col(d, collapse) for _, d in raters]
        exact = sum(1 for i in range(len(clips))
                    if len({c[i] for c in cols}) == 1) / len(clips)
        print(f"=== {label} ===")
        print(f"  raw exact agreement: {exact:.3f}")
        if len(raters) == 2:
            po, pe, k = cohen_kappa(cols[0], cols[1], cats)
            print(f"  Cohen's kappa: {k:.3f}  ({_interpret(k)})   [po={po:.3f} pe={pe:.3f}]")
            _confusion(cols[0], cols[1], cats,
                       (raters[0][0][:8], raters[1][0][:8]))
        else:
            per_item = []
            for i in range(len(clips)):
                per_item.append(Counter(c[i] for c in cols))
            pbar, pe, k = fleiss_kappa(per_item, cats, len(raters))
            print(f"  Fleiss' kappa: {k:.3f}  ({_interpret(k)})   [Pbar={pbar:.3f} Pe={pe:.3f}]")
        if collapse:
            verdict = "PASS" if k >= threshold else "FAIL"
            print(f"\n  ADR-0012 gate (binary kappa >= {threshold}): {verdict}  (kappa={k:.3f})")
        print()
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--labels", nargs="+", required=True, help="2+ label JSON files")
    ap.add_argument("--field", default="artifact", help="label key inside each clip record")
    ap.add_argument("--present", default="mild,strong",
                    help="comma list of categories that collapse to 'present'")
    ap.add_argument("--threshold", type=float, default=0.6)
    args = ap.parse_args()
    return run(args.labels, args.field,
               set(s.strip() for s in args.present.split(",") if s.strip()),
               args.threshold)


if __name__ == "__main__":
    raise SystemExit(main())
