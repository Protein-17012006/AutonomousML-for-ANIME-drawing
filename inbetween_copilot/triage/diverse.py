"""Diverse-lens calibrated triage gate. Adapts the MLT lens votes + the deterministic
softness/sharpness signals (different blind spots than the VLM) into CSQ channel
scores, then gates auto-clean through CSQ's calibrated decision. Reuses CSQ's
fusion+conformal and MLT's ClipTriage/package -- the only new code is the adapter,
the gate wiring, and the offline calibration driver."""
from __future__ import annotations

import json

from inbetween_copilot.qa.csq.verdict import ChannelScore, Decision
from inbetween_copilot.qa.csq.confidence import aggregate
from inbetween_copilot.qa.csq.conformal import Calibrator, fit
from benchmark.triage.aggregate import ClipTriage
from benchmark.lib.signals.spatial_quality import SPATIAL_THRESH

BASE_AUC = {"timing": 0.85, "identity": 0.85, "lineart": 0.85,
            "softness": 0.90, "sharpness": 0.70}
TAU_SOFT = 0.15
_VLM_LENSES = ("timing", "identity", "lineart")
_SCORE = {"flag": 1.0, "clean": 0.0, "unsure": 0.5}


def _clip01(x: float) -> float:
    x = float(x)
    return 0.0 if x < 0.0 else 1.0 if x > 1.0 else x


def to_channels(lens_votes: dict, soft: float, sharp: float) -> dict:
    def g(k):
        return _SCORE.get(lens_votes.get(k, {}).get("verdict"), 0.5)

    def f(k):
        return lens_votes.get(k, {}).get("verdict") == "flag"

    ch = {k: ChannelScore(k, g(k), f(k)) for k in _VLM_LENSES}
    ch["softness"] = ChannelScore("softness", _clip01(soft), float(soft) > TAU_SOFT)
    ch["sharpness"] = ChannelScore("sharpness", _clip01(sharp), float(sharp) > SPATIAL_THRESH)
    return ch


def channel_su(lens_votes: dict, soft: float, sharp: float):
    ch = to_channels(lens_votes, soft, sharp)
    flip = {n: 0.0 for n in ch}            # NO perturbation -> explicit 0 (else aggregate defaults to 1.0)
    return aggregate(ch, flip, base_auc=BASE_AUC)


def fit_calibrator(samples, *, alpha_miss: float = 0.05, u_max: float = 0.6, n_bins: int = 3) -> Calibrator:
    S, U, T = [], [], []
    for lv, soft, sharp, truth in samples:
        s, u = channel_su(lv, soft, sharp)
        S.append(s); U.append(u); T.append(bool(truth))
    return fit(S, U, T, alpha_miss=alpha_miss, u_max=u_max, n_bins=n_bins)


def save_calibrator(cal: Calibrator, path: str) -> None:
    with open(path, "w", encoding="utf-8") as f:
        json.dump({"a": cal.a, "b": cal.b, "u_edges": list(cal.u_edges),
                   "tau_pass": list(cal.tau_pass), "tau_flag": list(cal.tau_flag),
                   "u_max": cal.u_max, "alpha_miss": cal.alpha_miss}, f)


def load_calibrator(path: str) -> Calibrator:
    with open(path, encoding="utf-8") as f:
        d = json.load(f)
    return Calibrator(a=d["a"], b=d["b"], u_edges=tuple(d["u_edges"]),
                      tau_pass=tuple(d["tau_pass"]), tau_flag=tuple(d["tau_flag"]),
                      u_max=d["u_max"], alpha_miss=d["alpha_miss"])


def gate_clip(clip: str, lens_votes: dict, soft: float, sharp: float, calibrator) -> ClipTriage:
    """Gate a clip through the calibrated decision: PASS -> auto_clean, else disagree.
    Returns ClipTriage with all 5 channels (3 VLM + softness + sharpness)."""
    ch = to_channels(lens_votes, soft, sharp)
    flip = {n: 0.0 for n in ch}
    s, u = aggregate(ch, flip, base_auc=BASE_AUC)
    decision = "auto_clean" if calibrator.decide(s, u) == Decision.PASS else "disagree"
    n_flag = sum(1 for c in ch.values() if c.fires)               # fired channels across all 5
    n_unsure = sum(1 for k in _VLM_LENSES                          # softness/sharpness are deterministic -> never unsure
                   if lens_votes.get(k, {}).get("verdict") == "unsure")
    votes = {k: lens_votes.get(k, {"verdict": "unsure", "note": ""}) for k in _VLM_LENSES}
    votes["softness"] = {"verdict": "flag" if float(soft) > TAU_SOFT else "clean", "note": f"soft={soft:.3f}"}
    votes["sharpness"] = {"verdict": "flag" if float(sharp) > SPATIAL_THRESH else "clean", "note": f"sharp={sharp:.3f}"}
    return ClipTriage(clip, decision, votes, n_flag, n_unsure, False, float(u))
