"""Compatibility composition module for production co-pilot ports.

New callers should import :func:`build_real_ports` from
``inbetween_copilot.composition``. ``build_real_callables`` remains for callers
that still consume the historical dictionary contract.
"""
from __future__ import annotations

import dataclasses
import os
import sys

from inbetween_copilot.generate.correct import composite_region, hold_copy
from inbetween_copilot.generate.director import decide, decide_fixed
from inbetween_copilot.generate.localize import hold_fixable_fraction, localize_held_soft
from inbetween_copilot.generate.service import CorrectInbetween
from inbetween_copilot.infrastructure.vision_qa import VisionJSONQA
from inbetween_copilot.pipeline.ports import CopilotPorts
from inbetween_copilot.qa.csq.features import standard_channel_fns
from inbetween_copilot.qa.csq.stillness import (
    TAU_SRC_MOTION,
    TAU_STILL,
    motion_concentration,
    window_source_motion,
)
from inbetween_copilot.qa.gate import frame_qa_from_verdict
from inbetween_copilot.qa.perception import perceive, perceive_calibrated
from inbetween_copilot.reporting.charspec import (
    CharacterSpec,
    condition_qa_prompt,
    reference_frames_for_gen,
)
from inbetween_copilot.signals.motion import gap_score
from inbetween_copilot.signals.prompt import _MOTION_PROMPT
from inbetween_copilot.signals.regime import classify, scene_cut
from inbetween_copilot.signals.softness import interp_softness
from inbetween_copilot.triage.factory import make_triage_fn
from inbetween_copilot.triage.widegap import keys_from_gap


def build_real_ports(spec: "CharacterSpec | None", *, tau_hold: float, tau_snap: float,
                     rife_engine, anisora_gen, breakdown_supply=None,
                     vlm_fn=None, reason_fn=None, askkey_fn=None,
                     use_director: bool = True, csq_artifact=None,
                     ask_fn=None) -> CopilotPorts:
    """Compose pure policies with the concrete engines supplied by infrastructure."""

    def regime_fn(a, b):
        return classify(
            [gap_score(a, b)], tau_hold=tau_hold, tau_snap=tau_snap,
            has_cut=scene_cut(a, b),
        )

    def interp_fn(route, a, b):
        if route in ("hold", "snap_preserve"):
            return [a, a, b]
        return rife_engine(a, b)

    qa_fn = VisionJSONQA(condition_qa_prompt(_MOTION_PROMPT, spec))

    def softness_fn(frames):
        return float(interp_softness(frames)["soft_mean"])

    def gen_fn(a, m, b):
        return anisora_gen(a, m, b, references=reference_frames_for_gen(spec))

    def calibrated_verdict(frames):
        raw = (vlm_fn(frames) if vlm_fn is not None else None) or {}
        vlm_err = bool(raw.get("has_motion_error"))
        vlm_score = (
            raw.get("verdict_prob")
            if csq_artifact.vlm_mode == "continuous" else None
        )
        channel_fns = standard_channel_fns(
            vlm_err,
            tau_soft=csq_artifact.tau_soft,
            vlm_score=vlm_score,
            sharp_mode=getattr(csq_artifact, "sharp_mode", "absolute"),
        )
        return perceive_calibrated(
            frames,
            channel_fns=channel_fns,
            base_auc=csq_artifact.base_auc,
            calibrator=csq_artifact.calibrator,
            k=csq_artifact.k,
            lam=csq_artifact.lam,
            stillness_fn=motion_concentration,
            tau_still=csq_artifact.meta.get("tau_still", TAU_STILL),
            source_motion_fn=window_source_motion,
            tau_motion=csq_artifact.meta.get("tau_motion", TAU_SRC_MOTION),
        )

    def qa3_fn(frames):
        return frame_qa_from_verdict(calibrated_verdict(frames))

    def perceive_fn(frames):
        if csq_artifact is None:
            return perceive(
                frames,
                vlm_fn=vlm_fn,
                softness_fn=softness_fn,
                holdfix_fn=hold_fixable_fraction,
            )
        verdict = calibrated_verdict(frames)
        try:
            hold_fixable = float(hold_fixable_fraction(frames))
        except Exception:
            hold_fixable = 0.0
        return dataclasses.replace(verdict, hold_fixable=hold_fixable)

    def decide_fn(verdict, region, attempts):
        if use_director and reason_fn is not None:
            return decide(verdict, region, attempts, reason_fn=reason_fn)
        return decide_fixed(verdict, region, attempts)

    def refill_fn(frames, a, b, region):
        if not region.mask:
            return list(frames)
        return composite_region(frames, hold_copy(a, b, len(frames)), region)

    def escalate_fn(a, b):
        return anisora_gen(a, a, b, references=reference_frames_for_gen(spec))

    def split_fill_fn(a, m, b):
        return rife_engine(a, m) + rife_engine(m, b)

    corrector = CorrectInbetween(
        perceive_fn=perceive_fn,
        localize_fn=localize_held_soft,
        decide_fn=decide_fn,
        refill_fn=refill_fn,
        escalate_fn=escalate_fn,
        askkey_fn=askkey_fn or (lambda a, b: None),
        split_fill_fn=split_fill_fn,
    ).execute

    return CopilotPorts(
        gap_fn=gap_score,
        regime_fn=regime_fn,
        interp_fn=interp_fn,
        qa_fn=qa_fn,
        softness_fn=softness_fn,
        triage_fn=make_triage_fn(
            tau_hold=tau_hold, tau_snap=tau_snap, ask_fn=ask_fn,
        ),
        keys_needed_fn=keys_from_gap,
        gen_fn=gen_fn,
        breakdown_supply=breakdown_supply,
        corrector=corrector,
        qa3_fn=qa3_fn if csq_artifact is not None else None,
        qa_window=True,
    )


def build_real_callables(*args, **kwargs) -> dict:
    """Compatibility facade for the legacy dictionary contract."""
    return build_real_ports(*args, **kwargs).as_kwargs()


def _assert_max_pixels_320():
    """Abort when the served VLM resolution does not match calibration."""
    max_pixels = os.environ.get("VISION_MAX_PIXELS_CHECK")
    if max_pixels is None:
        print(
            "[WARN] VISION_MAX_PIXELS_CHECK not set -- cannot verify "
            "served max_pixels==320",
            file=sys.stderr,
        )
    elif max_pixels != "320":
        raise SystemExit(
            f"[ABORT] served max_pixels={max_pixels!r}, expected 320"
        )
