"""The shipped CSQ artifact: a fitted Calibrator + the channel base-AUC weights +
the few inference knobs the live path needs ("fit-once, serve"). Persisted as a
small JSON the product loads at startup. encoding="utf-8" everywhere (the Windows
save/load lesson from the triage calibrator, commit d1f63c1)."""
from __future__ import annotations

import json
from dataclasses import dataclass, field

from inbetween_copilot.qa.csq.conformal import Calibrator


@dataclass(frozen=True)
class CSQArtifact:
    calibrator: Calibrator
    base_auc: dict
    tau_soft: float = 0.15
    k: int = 4
    lam: float = 0.5
    version: str = "v1"
    vlm_mode: str = "binary"        # "binary" {0,1} | "continuous" verdict_prob (§5k)
    sharp_mode: str = "absolute"    # "absolute" clip_score | "relative" soft_worst (§5m cross-show fix)
    meta: dict = field(default_factory=dict)


def _cal_to_dict(c: Calibrator) -> dict:
    return {"a": c.a, "b": c.b, "u_edges": list(c.u_edges),
            "tau_pass": list(c.tau_pass), "tau_flag": list(c.tau_flag),
            "u_max": c.u_max, "alpha_miss": c.alpha_miss}


def _cal_from_dict(d: dict) -> Calibrator:
    return Calibrator(a=d["a"], b=d["b"], u_edges=tuple(d["u_edges"]),
                      tau_pass=tuple(d["tau_pass"]), tau_flag=tuple(d["tau_flag"]),
                      u_max=d["u_max"], alpha_miss=d["alpha_miss"])


def save_artifact(art: CSQArtifact, path: str) -> None:
    with open(path, "w", encoding="utf-8") as f:
        json.dump({"calibrator": _cal_to_dict(art.calibrator),
                   "base_auc": art.base_auc, "tau_soft": art.tau_soft,
                   "k": art.k, "lam": art.lam, "version": art.version,
                   "vlm_mode": art.vlm_mode, "sharp_mode": art.sharp_mode,
                   "meta": art.meta}, f, indent=2)


def load_artifact(path: str) -> CSQArtifact:
    with open(path, encoding="utf-8") as f:
        d = json.load(f)
    return CSQArtifact(calibrator=_cal_from_dict(d["calibrator"]),
                       base_auc=dict(d["base_auc"]), tau_soft=d.get("tau_soft", 0.15),
                       k=d.get("k", 4), lam=d.get("lam", 0.5),
                       version=d.get("version", "v1"), vlm_mode=d.get("vlm_mode", "binary"),
                       sharp_mode=d.get("sharp_mode", "absolute"), meta=d.get("meta", {}))
