"""Signal + VLM fusion for the visual-integrity (artifact) axis — ADR-0012 fusion arm.

WHY fusion. The VLM (`motion_lora16_rife`) is a high-precision GROSS detector: it
catches morph/warp/melt but is semantically blind to subtle within-shot wobble —
proven this session, the prompt lever (artifact arm) AND the resolution lever
(native 720x480) both changed nothing. The DINO signal (`identity_signal.py`,
~0.80 AUC vs corrected labels) is a magnitude estimator: it fires on the subtle
degradation the VLM misses, but also on intended motion (head-turns, bg-pan, VFX).
Neither alone is enough; their blind spots are complementary.

RULE: present = vlm_error OR (signal_metric >= tau).
The VLM contributes precision on gross errors (it is right when it fires); the
signal threshold recovers the subtle hole. tau is calibrated by F1 — but reported
under LEAVE-ONE-OUT cross-validation because suite_integrity is small (n=42) and an
in-sample best tau would overstate the gain. The in-sample number is also printed,
explicitly labelled as the optimistic ceiling.

GPU-free: consumes cached VLM verdicts + cached signal scores.
    python -m benchmark.lib.signals.fusion --vlm <probe.json> --signal <signal.json> --metric worst_jump
"""
from __future__ import annotations

import argparse
import json

LABELS = ".scratch/motion_labels/artifact_final.json"


def prf(preds, truth):
    tp = sum(1 for p, t in zip(preds, truth) if p and t)
    fp = sum(1 for p, t in zip(preds, truth) if p and not t)
    fn = sum(1 for p, t in zip(preds, truth) if (not p) and t)
    prec = tp / (tp + fp) if tp + fp else 0.0
    rec = tp / (tp + fn) if tp + fn else 0.0
    f1 = 2 * prec * rec / (prec + rec) if prec + rec else 0.0
    return {"precision": round(prec, 3), "recall": round(rec, 3),
            "f1": round(f1, 3), "tp": tp, "fp": fp, "fn": fn}


def _tau_candidates(sigs):
    s = sorted(set(sigs))
    cands = [s[0] - 1e-6]
    for a, b in zip(s, s[1:]):
        cands.append((a + b) / 2.0)
    cands.append(s[-1] + 1e-6)
    return cands


def best_tau(idx, vlm, sig, truth):
    """tau maximizing F1 of (vlm OR sig>=tau) over the given index subset.
    Tie-break toward the LARGER tau (fewer signal FPs, more VLM-like)."""
    sub_sig = [sig[i] for i in idx]
    best, best_f1 = None, -1.0
    for tau in _tau_candidates(sub_sig):
        preds = [vlm[i] or sig[i] >= tau for i in idx]
        f1 = prf(preds, [truth[i] for i in idx])["f1"]
        if f1 >= best_f1:          # >= keeps the largest tau among ties
            best_f1, best = f1, tau
    return best


def loo(vlm, sig, truth, *, use_vlm=True):
    """Leave-one-out fusion (or signal-alone if use_vlm=False) predictions."""
    n = len(truth)
    v = vlm if use_vlm else [False] * n
    preds = []
    for i in range(n):
        idx = [j for j in range(n) if j != i]
        tau = best_tau(idx, v, sig, truth)
        preds.append(v[i] or sig[i] >= tau)
    return preds


def insample(vlm, sig, truth, *, use_vlm=True):
    n = len(truth)
    v = vlm if use_vlm else [False] * n
    tau = best_tau(list(range(n)), v, sig, truth)
    return [v[i] or sig[i] >= tau for i in range(n)], tau


def run(vlm_path, sig_path, metric):
    lab = {c["clip"]: c for c in json.load(open(LABELS))["clips"]}
    vlm_v = json.load(open(vlm_path))["verdicts"]
    sig_d = {c["clip"]: c for c in json.load(open(sig_path))["clips"]}
    clips = [c for c in lab if c in vlm_v and c in sig_d]

    truth = [lab[c]["artifact"] in ("mild", "strong") for c in clips]
    vlm = [bool(vlm_v[c].get("has_motion_error")) for c in clips]
    sig = [float(sig_d[c][metric]) for c in clips]
    hole = {c for c in clips
            if lab[c]["identity_role"] == "clean" and lab[c]["artifact"] != "none"}

    print(f"suite_integrity n={len(clips)}  present={sum(truth)}  "
          f"metric={metric}  vlm={vlm_path.split('/')[-1]}\n")
    vlm_only = prf(vlm, truth)
    sig_loo = prf(loo(vlm, sig, truth, use_vlm=False), truth)
    fus_loo_preds = loo(vlm, sig, truth, use_vlm=True)
    fus_loo = prf(fus_loo_preds, truth)
    fus_in_preds, tau_in = insample(vlm, sig, truth, use_vlm=True)
    fus_in = prf(fus_in_preds, truth)

    def line(name, m):
        print(f"  {name:<26} P={m['precision']:.3f} R={m['recall']:.3f} "
              f"F1={m['f1']:.3f}  (tp={m['tp']} fp={m['fp']} fn={m['fn']})")
    line("VLM alone (artifact)", vlm_only)
    line("signal alone (LOO)", sig_loo)
    line("FUSION VLM+signal (LOO)", fus_loo)
    line("FUSION (in-sample ceiling)", fus_in)
    print(f"  [in-sample tau={tau_in:.4f}]")

    # what fusion newly recovers vs VLM-alone, and any new FPs
    newly = [c for c, fp_, v in zip(clips, fus_loo_preds, vlm)
             if fp_ and not v and lab[c]["artifact"] in ("mild", "strong")]
    newfp = [c for c, fp_, v in zip(clips, fus_loo_preds, vlm)
             if fp_ and not v and lab[c]["artifact"] == "none"]
    hole_caught = [c for c, fp_ in zip(clips, fus_loo_preds) if fp_ and c in hole]
    print(f"\n  hole(clean+artifact) caught by FUSION: {len(hole_caught)}/{len(hole)} "
          f"(VLM-alone caught {sum(1 for c in hole if vlm[clips.index(c)])})")
    print(f"  newly recovered (true, VLM missed): {sorted(newly)}")
    print(f"  new false positives from signal:    {sorted(newfp)}")
    return {"metric": metric, "vlm_only": vlm_only, "signal_loo": sig_loo,
            "fusion_loo": fus_loo, "fusion_insample": fus_in}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--vlm", default=".scratch/motion_labels/probe_lora320.json")
    ap.add_argument("--signal", default=".scratch/motion_labels/signal_v2.json")
    ap.add_argument("--metric", default="worst_jump")
    a = ap.parse_args()
    run(a.vlm, a.signal, a.metric)


if __name__ == "__main__":
    raise SystemExit(main())
