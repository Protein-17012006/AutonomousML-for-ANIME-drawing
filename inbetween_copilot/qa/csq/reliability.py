"""U6 -- the reliability metrics. Pure functions over (calibrated probabilities,
3-state decisions, ground truth) producing the four campaign numbers: ECE
(is p_error honest?), the risk-coverage trade (the abstain governor),
verdict flip-rate (robustness), and Goodhart-pass-rate (gaming resistance)."""
from __future__ import annotations


def ece(p_list, truth, *, n_bins: int = 10) -> float:
    n = len(p_list)
    if n == 0:
        return 0.0
    total = 0.0
    for j in range(n_bins):
        lo, hi = j / n_bins, (j + 1) / n_bins
        idx = [i for i, p in enumerate(p_list)
               if (p > lo or j == 0) and p <= hi]
        if not idx:
            continue
        conf = sum(p_list[i] for i in idx) / len(idx)
        acc = sum(truth[i] for i in idx) / len(idx)
        total += (len(idx) / n) * abs(conf - acc)
    return total


def risk_coverage(decisions, truth) -> dict:
    n = len(decisions)
    if n == 0:
        return {"coverage": 0.0, "abstain_rate": 0.0,
                "pass_miss_rate": 0.0, "flag_false_alarm": 0.0}
    passes = [(d, t) for d, t in zip(decisions, truth) if d == "pass"]
    flags = [(d, t) for d, t in zip(decisions, truth) if d == "flag"]
    abstains = sum(1 for d in decisions if d == "abstain")
    return {
        "coverage": (n - abstains) / n,
        "abstain_rate": abstains / n,
        "pass_miss_rate": (sum(t for _, t in passes) / len(passes)) if passes else 0.0,
        "flag_false_alarm": (sum(1 - t for _, t in flags) / len(flags)) if flags else 0.0,
    }


def flip_rate_metric(decisions_orig, decisions_perturbed) -> float:
    n = len(decisions_orig)
    if n == 0:
        return 0.0
    return sum(1 for a, b in zip(decisions_orig, decisions_perturbed) if a != b) / n


def goodhart_pass_rate(decisions, gamed) -> float:
    idx = [i for i, g in enumerate(gamed) if g]
    if not idx:
        return 0.0
    return sum(1 for i in idx if decisions[i] == "pass") / len(idx)
