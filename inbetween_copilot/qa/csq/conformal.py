"""U4 -- the conformal decider. Calibrates the raw error-score `s` into an honest
probability (Platt), then sets uncertainty-conditioned pass/flag thresholds with a
coverage target: auto-passed frames carry <= alpha_miss empirical missed-error on
the calibration set. The hard u_max gate forces abstain on high-uncertainty (and
out-of-distribution / gamed) frames regardless of score."""
from __future__ import annotations

import math
from dataclasses import dataclass

from inbetween_copilot.qa.csq.verdict import Decision


def _sigmoid(z: float) -> float:
    if z >= 0:
        return 1.0 / (1.0 + math.exp(-z))
    e = math.exp(z)
    return e / (1.0 + e)


@dataclass(frozen=True)
class Calibrator:
    a: object            # float | None (None = unfit -> always abstain)
    b: object
    u_edges: tuple
    tau_pass: tuple
    tau_flag: tuple
    u_max: float
    alpha_miss: float

    def p_error(self, s: float) -> float:
        if self.a is None:
            return 1.0
        return _sigmoid(self.a * s + self.b)

    def _bin(self, u: float) -> int:
        for j in range(len(self.u_edges) - 1):
            if u <= self.u_edges[j + 1]:
                return j
        return len(self.u_edges) - 2

    def decide(self, s: float, u: float) -> Decision:
        if self.a is None:
            return Decision.ABSTAIN
        if u > self.u_max:
            return Decision.ABSTAIN
        j = self._bin(u)
        p = self.p_error(s)
        if p <= self.tau_pass[j]:
            return Decision.PASS
        if p >= self.tau_flag[j]:
            return Decision.FLAG
        return Decision.ABSTAIN


def _fit_platt(s, truth, iters, lr):
    a, b = 0.0, 0.0
    n = len(s)
    for _ in range(iters):
        ga, gb = 0.0, 0.0
        for si, ti in zip(s, truth):
            p = _sigmoid(a * si + b)
            ga += (p - ti) * si
            gb += (p - ti)
        a -= lr * ga / n
        b -= lr * gb / n
    return a, b


def _tau_pass(ps, truth, alpha):
    """Largest cutoff c s.t. among p<=c the empirical error rate <= alpha."""
    best = 0.0
    for c in sorted(set(ps)):
        region = [t for p, t in zip(ps, truth) if p <= c]
        if region and (sum(region) / len(region)) <= alpha:
            best = c
    return best


def _tau_flag(ps, truth, alpha):
    """Smallest cutoff c s.t. among p>=c the empirical clean rate <= alpha."""
    best = 1.0
    for c in sorted(set(ps), reverse=True):
        region = [t for p, t in zip(ps, truth) if p >= c]
        if region and (sum(1 - t for t in region) / len(region)) <= alpha:
            best = c
    return best


def fit(cal_s, cal_u, cal_truth, *, alpha_miss=0.05, u_max=0.6,
        n_bins=3, iters=800, lr=0.5) -> Calibrator:
    a, b = _fit_platt(cal_s, cal_truth, iters, lr)
    edges = tuple(j / n_bins for j in range(n_bins + 1))   # equal-width over [0,1]
    tau_pass, tau_flag = [], []
    for j in range(n_bins):
        lo, hi = edges[j], edges[j + 1]
        idx = [i for i, u in enumerate(cal_u)
               if (u > lo or j == 0) and u <= hi]
        if not idx:
            tau_pass.append(0.0)
            tau_flag.append(1.0)
            continue
        ps = [_sigmoid(a * cal_s[i] + b) for i in idx]
        tr = [cal_truth[i] for i in idx]
        tau_pass.append(_tau_pass(ps, tr, alpha_miss))
        tau_flag.append(_tau_flag(ps, tr, alpha_miss))
    return Calibrator(a=a, b=b, u_edges=edges, tau_pass=tuple(tau_pass),
                      tau_flag=tuple(tau_flag), u_max=u_max, alpha_miss=alpha_miss)
