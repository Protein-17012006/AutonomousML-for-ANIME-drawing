"""Fit + freeze the v3 CSQ Calibrator: continuous VLM (§5k) + CONTENT-RELATIVE
sharpness (§5m — interp_softness.soft_worst instead of the absolute clip_score whose
hardcoded LAP_REF miscalibrates across shows). Reproducible: reads the frozen
suite_csq_calibration manifest (split, truth, cached vlm, served verdict_prob) +
recomputes the channels from the frozen suite_smallgap frames. Fits on the 4 SHIP
fit-series -> artifacts/csq_smallgap_v3.json (vlm_mode=continuous, sharp_mode=relative).

    python -m inbetween_copilot.calibration.fit_artifact_v3
"""
from __future__ import annotations

import glob
import json
import os

import numpy as np
from PIL import Image

from inbetween_copilot.qa.csq.conformal import fit
from inbetween_copilot.qa.csq.artifact import CSQArtifact, save_artifact
from inbetween_copilot.qa.csq.features import clip_su

CALIB = "benchmark/suites/suite_csq_calibration/manifest.json"
SMALLGAP = "benchmark/suites/suite_smallgap/clips"
OUT = "inbetween_copilot/artifacts/csq_smallgap_v3.json"
BASE_AUC = {"vlm": 0.90, "softness": 0.90, "sharpness": 0.70}
TAU_SOFT, K = 0.15, 4
ALPHA_MISS, U_MAX, N_BINS = 0.05, 0.6, 3


def _load(cid):
    return [np.array(Image.open(p).convert("RGB"))
            for p in sorted(glob.glob(f"{SMALLGAP}/{cid}/*.png"))]


def main() -> int:
    clips = json.load(open(CALIB, encoding="utf-8"))["clips"]
    S, U, T = [], [], []
    for c in clips:
        if c["split"] != "fit" or c.get("verdict_prob") is None:
            continue
        s, u = clip_su(_load(c["id"]), bool(c["vlm"]), base_auc=BASE_AUC, tau_soft=TAU_SOFT,
                       k=K, vlm_score=float(c["verdict_prob"]), sharp_mode="relative")
        S.append(s); U.append(u); T.append(bool(c["truth"]))
    cal = fit(S, U, T, alpha_miss=ALPHA_MISS, u_max=U_MAX, n_bins=N_BINS)
    art = CSQArtifact(calibrator=cal, base_auc=BASE_AUC, tau_soft=TAU_SOFT, k=K, lam=0.5,
                      version="smallgap_v3", vlm_mode="continuous", sharp_mode="relative",
                      meta={"suite": "suite_smallgap", "n_fit": len(S), "n_err": int(sum(T)),
                            "note": "continuous VLM + content-relative sharpness (soft_worst); §5k+§5m"})
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    save_artifact(art, OUT)
    print(f"v3 fit n={len(S)} err={int(sum(T))} -> {OUT}")
    print(f"  a={cal.a:.4f} b={cal.b:.4f} tau_pass={tuple(round(x,3) for x in cal.tau_pass)} "
          f"tau_flag={tuple(round(x,3) for x in cal.tau_flag)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
