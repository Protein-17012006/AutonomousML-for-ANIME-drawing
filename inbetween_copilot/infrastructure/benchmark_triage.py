"""Adapter between internal CSQ values and the benchmark triage package."""
from __future__ import annotations

import json

from benchmark.lib.signals.spatial_quality import SPATIAL_THRESH
from benchmark.triage.aggregate import ClipTriage

from inbetween_copilot.qa.csq.confidence import aggregate
from inbetween_copilot.qa.csq.conformal import Calibrator, fit
from inbetween_copilot.qa.csq.verdict import ChannelScore, Decision

BASE_AUC = {
    "timing": 0.85, "identity": 0.85, "lineart": 0.85,
    "softness": 0.90, "sharpness": 0.70,
}
TAU_SOFT = 0.15
_VLM_LENSES = ("timing", "identity", "lineart")
_SCORE = {"flag": 1.0, "clean": 0.0, "unsure": 0.5}


def _clip01(value: float) -> float:
    value = float(value)
    return 0.0 if value < 0.0 else 1.0 if value > 1.0 else value


def to_channels(lens_votes: dict, soft: float, sharp: float) -> dict:
    def score(name):
        return _SCORE.get(lens_votes.get(name, {}).get("verdict"), 0.5)

    def fires(name):
        return lens_votes.get(name, {}).get("verdict") == "flag"

    channels = {
        name: ChannelScore(name, score(name), fires(name))
        for name in _VLM_LENSES
    }
    channels["softness"] = ChannelScore(
        "softness", _clip01(soft), float(soft) > TAU_SOFT,
    )
    channels["sharpness"] = ChannelScore(
        "sharpness", _clip01(sharp), float(sharp) > SPATIAL_THRESH,
    )
    return channels


def channel_su(lens_votes: dict, soft: float, sharp: float):
    channels = to_channels(lens_votes, soft, sharp)
    return aggregate(
        channels, {name: 0.0 for name in channels}, base_auc=BASE_AUC,
    )


def fit_calibrator(samples, *, alpha_miss: float = 0.05,
                   u_max: float = 0.6, n_bins: int = 3) -> Calibrator:
    scores, uncertainties, truth = [], [], []
    for lens_votes, soft, sharp, target in samples:
        score, uncertainty = channel_su(lens_votes, soft, sharp)
        scores.append(score)
        uncertainties.append(uncertainty)
        truth.append(bool(target))
    return fit(
        scores, uncertainties, truth,
        alpha_miss=alpha_miss, u_max=u_max, n_bins=n_bins,
    )


def save_calibrator(calibrator: Calibrator, path: str) -> None:
    with open(path, "w", encoding="utf-8") as handle:
        json.dump({
            "a": calibrator.a,
            "b": calibrator.b,
            "u_edges": list(calibrator.u_edges),
            "tau_pass": list(calibrator.tau_pass),
            "tau_flag": list(calibrator.tau_flag),
            "u_max": calibrator.u_max,
            "alpha_miss": calibrator.alpha_miss,
        }, handle)


def load_calibrator(path: str) -> Calibrator:
    with open(path, encoding="utf-8") as handle:
        document = json.load(handle)
    return Calibrator(
        a=document["a"], b=document["b"],
        u_edges=tuple(document["u_edges"]),
        tau_pass=tuple(document["tau_pass"]),
        tau_flag=tuple(document["tau_flag"]),
        u_max=document["u_max"], alpha_miss=document["alpha_miss"],
    )


def gate_clip(clip: str, lens_votes: dict, soft: float, sharp: float,
              calibrator) -> ClipTriage:
    channels = to_channels(lens_votes, soft, sharp)
    score, uncertainty = aggregate(
        channels, {name: 0.0 for name in channels}, base_auc=BASE_AUC,
    )
    decision = (
        "auto_clean"
        if calibrator.decide(score, uncertainty) == Decision.PASS
        else "disagree"
    )
    n_flag = sum(1 for channel in channels.values() if channel.fires)
    n_unsure = sum(
        1 for name in _VLM_LENSES
        if lens_votes.get(name, {}).get("verdict") == "unsure"
    )
    votes = {
        name: lens_votes.get(name, {"verdict": "unsure", "note": ""})
        for name in _VLM_LENSES
    }
    votes["softness"] = {
        "verdict": "flag" if float(soft) > TAU_SOFT else "clean",
        "note": f"soft={soft:.3f}",
    }
    votes["sharpness"] = {
        "verdict": "flag" if float(sharp) > SPATIAL_THRESH else "clean",
        "note": f"sharp={sharp:.3f}",
    }
    return ClipTriage(
        clip, decision, votes, n_flag, n_unsure, False, float(uncertainty),
    )
