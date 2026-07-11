"""JSON adapter for the CSQ artifact persistence port."""
from __future__ import annotations

import json

from inbetween_copilot.qa.csq.models import (
    CSQArtifact,
    calibrator_from_dict,
    calibrator_to_dict,
)


class CSQArtifactJsonStore:
    def save(self, artifact: CSQArtifact, path: str) -> None:
        with open(path, "w", encoding="utf-8") as handle:
            json.dump({
                "calibrator": calibrator_to_dict(artifact.calibrator),
                "base_auc": artifact.base_auc,
                "tau_soft": artifact.tau_soft,
                "k": artifact.k,
                "lam": artifact.lam,
                "version": artifact.version,
                "vlm_mode": artifact.vlm_mode,
                "sharp_mode": artifact.sharp_mode,
                "meta": artifact.meta,
            }, handle, indent=2)

    def load(self, path: str) -> CSQArtifact:
        with open(path, encoding="utf-8") as handle:
            document = json.load(handle)
        return CSQArtifact(
            calibrator=calibrator_from_dict(document["calibrator"]),
            base_auc=dict(document["base_auc"]),
            tau_soft=document.get("tau_soft", 0.15),
            k=document.get("k", 4),
            lam=document.get("lam", 0.5),
            version=document.get("version", "v1"),
            vlm_mode=document.get("vlm_mode", "binary"),
            sharp_mode=document.get("sharp_mode", "absolute"),
            meta=document.get("meta", {}),
        )
