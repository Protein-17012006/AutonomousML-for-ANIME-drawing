"""Build the binary and calibrated QA capabilities used by the pipeline."""
from __future__ import annotations

import dataclasses
import math
from dataclasses import dataclass
from typing import Callable

from inbetween_copilot.domain.character import CharacterSpec, condition_qa_prompt
from inbetween_copilot.generate.localize import hold_fixable_fraction
from inbetween_copilot.infrastructure.vision_qa import VisionJSONQA
from inbetween_copilot.qa.csq.features import standard_channel_fns
from inbetween_copilot.qa.csq.models import CSQArtifact
from inbetween_copilot.qa.csq.stillness import (
    TAU_SRC_MOTION,
    TAU_STILL,
    motion_concentration,
    window_source_motion,
)
from inbetween_copilot.qa.gate import frame_qa_from_verdict
from inbetween_copilot.qa.models import QAVerdict
from inbetween_copilot.qa.perception import perceive, perceive_calibrated
from inbetween_copilot.signals.prompt import _MOTION_PROMPT
from inbetween_copilot.signals.softness import interp_softness


@dataclass(frozen=True)
class QAComponents:
    qa_fn: Callable
    softness_fn: Callable
    perceive_fn: Callable
    qa3_fn: "Callable | None"


@dataclass(frozen=True)
class CalibratedVerdictEvaluator:
    """Validate the required VLM channel, then run calibrated CSQ policy."""

    artifact: CSQArtifact
    vlm_fn: "Callable | None"
    softness_fn: Callable

    def __call__(self, frames) -> QAVerdict:
        try:
            raw = self.vlm_fn(frames) if self.vlm_fn is not None else None
        except Exception:
            raw = None

        probability = None
        vlm_available = (
            isinstance(raw, dict)
            and raw.get("available", True) is not False
            and "has_motion_error" in raw
            and isinstance(raw.get("has_motion_error"), bool)
        )
        if vlm_available and self.artifact.vlm_mode == "continuous":
            try:
                probability = float(raw.get("verdict_prob"))
                vlm_available = (
                    not isinstance(raw.get("verdict_prob"), bool)
                    and math.isfinite(probability)
                    and 0.0 <= probability <= 1.0
                )
            except (TypeError, ValueError):
                vlm_available = False

        if not vlm_available:
            try:
                soft = float(self.softness_fn(frames))
            except Exception:
                soft = 0.0
            return QAVerdict(
                has_error=True,
                err_type="vlm_unavailable",
                region_hint="whole",
                explanation="required VLM channel unavailable",
                softness=soft,
                decision="abstain",
                p_error=0.5,
                u=1.0,
            )

        channel_fns = standard_channel_fns(
            bool(raw.get("has_motion_error")),
            tau_soft=self.artifact.tau_soft,
            vlm_score=(probability if self.artifact.vlm_mode == "continuous" else None),
            sharp_mode=self.artifact.sharp_mode,
        )
        return perceive_calibrated(
            frames,
            channel_fns=channel_fns,
            base_auc=self.artifact.base_auc,
            calibrator=self.artifact.calibrator,
            k=self.artifact.k,
            lam=self.artifact.lam,
            stillness_fn=motion_concentration,
            tau_still=self.artifact.meta.get("tau_still", TAU_STILL),
            source_motion_fn=window_source_motion,
            tau_motion=self.artifact.meta.get("tau_motion", TAU_SRC_MOTION),
        )


def build_qa_components(
    spec: "CharacterSpec | None",
    *,
    vlm_fn=None,
    csq_artifact: "CSQArtifact | None" = None,
) -> QAComponents:
    binary_qa = VisionJSONQA(condition_qa_prompt(_MOTION_PROMPT, spec))

    def softness_fn(frames) -> float:
        return float(interp_softness(frames)["soft_mean"])

    if csq_artifact is None:
        def perceive_fn(frames):
            return perceive(
                frames,
                vlm_fn=vlm_fn,
                softness_fn=softness_fn,
                holdfix_fn=hold_fixable_fraction,
            )

        return QAComponents(binary_qa, softness_fn, perceive_fn, None)

    calibrated = CalibratedVerdictEvaluator(csq_artifact, vlm_fn, softness_fn)

    def qa3_fn(frames):
        return frame_qa_from_verdict(calibrated(frames))

    def perceive_fn(frames):
        verdict = calibrated(frames)
        try:
            hold_fixable = float(hold_fixable_fraction(frames))
        except Exception:
            hold_fixable = 0.0
        return dataclasses.replace(verdict, hold_fixable=hold_fixable)

    return QAComponents(binary_qa, softness_fn, perceive_fn, qa3_fn)
