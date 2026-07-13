"""Domain values contained in a fitted CSQ artifact."""
from __future__ import annotations

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
    vlm_mode: str = "binary"
    sharp_mode: str = "absolute"
    meta: dict = field(default_factory=dict)


def calibrator_to_dict(calibrator: Calibrator) -> dict:
    return {
        "a": calibrator.a,
        "b": calibrator.b,
        "u_edges": list(calibrator.u_edges),
        "tau_pass": list(calibrator.tau_pass),
        "tau_flag": list(calibrator.tau_flag),
        "u_max": calibrator.u_max,
        "alpha_miss": calibrator.alpha_miss,
    }


def calibrator_from_dict(document: dict) -> Calibrator:
    return Calibrator(
        a=document["a"], b=document["b"],
        u_edges=tuple(document["u_edges"]),
        tau_pass=tuple(document["tau_pass"]),
        tau_flag=tuple(document["tau_flag"]),
        u_max=document["u_max"], alpha_miss=document["alpha_miss"],
    )
