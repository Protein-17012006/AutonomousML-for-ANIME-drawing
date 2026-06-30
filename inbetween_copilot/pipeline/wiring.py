# inbetween_copilot/pipeline/wiring.py
"""Operational entrypoint: bind the real engines/QA into run_copilot.

regime_fn   = smallgap.regime.classify over the pair's single step
interp_fn   = hold/snap copy, or RIFE+hold-aware for small motion (box)
qa_fn       = vision_common.vision_json with the (optionally spec-conditioned) prompt
softness_fn = smallgap.softness_signal.interp_softness -> soft_mean
gen_fn      = AniSora reference-conditioned A->M->B (box script)
"""
from __future__ import annotations

import argparse
import dataclasses
import os
import sys

from inbetween_copilot.signals.motion import gap_score
from inbetween_copilot.signals.regime import classify, scene_cut
from inbetween_copilot.signals.softness import interp_softness
from inbetween_copilot.signals.prompt import _MOTION_PROMPT   # the exact validated detector prompt
from inbetween_copilot.pipeline.copilot import run_copilot, CopilotCfg
from inbetween_copilot.reporting.report import summarize
from inbetween_copilot.reporting.charspec import (CharacterSpec, condition_qa_prompt,
                                        reference_frames_for_gen)
from inbetween_copilot.qa.perception import perceive, perceive_calibrated, PERCEPTION_PROMPT
from inbetween_copilot.qa.gate import frame_qa_from_verdict
from inbetween_copilot.qa.csq.artifact import load_artifact
from inbetween_copilot.qa.csq.features import standard_channel_fns
from inbetween_copilot.qa.csq.stillness import (motion_concentration, TAU_STILL,
                                             window_source_motion, TAU_SRC_MOTION)
from inbetween_copilot.generate.localize import localize_held_soft, hold_fixable_fraction
from inbetween_copilot.generate.director import decide, decide_fixed
from inbetween_copilot.generate.correct import composite_region, hold_copy
from inbetween_copilot.generate.correction import correct_inbetween


def build_real_callables(spec: "CharacterSpec | None", *, tau_hold: float, tau_snap: float,
                         rife_engine, anisora_gen, breakdown_supply=None,
                         vlm_fn=None, reason_fn=None, askkey_fn=None,
                         use_director: bool = True, csq_artifact=None) -> dict:
    def regime_fn(a, b):
        return classify([gap_score(a, b)], tau_hold=tau_hold, tau_snap=tau_snap,
                        has_cut=scene_cut(a, b))

    def interp_fn(route, a, b):
        if route in ("hold", "snap_preserve"):
            return [a, a, b]            # copy/keep timing, never morph
        return rife_engine(a, b)        # small -> RIFE + hold-aware (box)

    prompt = condition_qa_prompt(_MOTION_PROMPT, spec)

    def qa_fn(frames):
        # vision_json takes (prompt, image_paths) — write frames to temp PNGs and
        # read the validated detector's verdict key, identical to motion_arms._run_arm.
        import tempfile
        from PIL import Image
        from vision_common import vision_json
        tmpdir = tempfile.mkdtemp(prefix="copilot_qa_")
        paths = []
        for i, fr in enumerate(frames):
            p = os.path.join(tmpdir, f"{i:04d}.png")
            Image.fromarray(fr).save(p)
            paths.append(p)
        reply = vision_json(prompt, paths, tier="check", max_tokens=800)
        return bool(reply.get("has_motion_error"))

    def softness_fn(frames):
        return float(interp_softness(frames)["soft_mean"])

    def gen_fn(a, m, b):
        return anisora_gen(a, m, b, references=reference_frames_for_gen(spec))

    # --- calibrated self-QA (CSQ) wiring, behind the artifact flag (CSQ Design §5d) ---
    def _calibrated_verdict(frames):
        # VLM is a CONSTANT channel under perturbation (computed once, flip_rate 0) --
        # faithful to the Phase-1 calibration and 1 real VLM call; softness/sharpness
        # recompute per perturbed view (the shared standard_channel_fns definition).
        raw = (vlm_fn(frames) if vlm_fn is not None else None) or {}
        vlm_err = bool(raw.get("has_motion_error"))
        # §5k: a continuous artifact reads the served verdict_prob (P(error)); the
        # binary artifact ignores it and uses the {0,1} verdict.
        vlm_score = raw.get("verdict_prob") if csq_artifact.vlm_mode == "continuous" else None
        channel_fns = standard_channel_fns(vlm_err, tau_soft=csq_artifact.tau_soft,
                                           vlm_score=vlm_score,
                                           sharp_mode=getattr(csq_artifact, "sharp_mode", "absolute"))
        return perceive_calibrated(frames, channel_fns=channel_fns,
                                   base_auc=csq_artifact.base_auc,
                                   calibrator=csq_artifact.calibrator,
                                   k=csq_artifact.k, lam=csq_artifact.lam,
                                   stillness_fn=motion_concentration,        # §5h anti-Goodhart guard
                                   tau_still=csq_artifact.meta.get("tau_still", TAU_STILL),
                                   source_motion_fn=window_source_motion,    # §5n recall guard
                                   tau_motion=csq_artifact.meta.get("tau_motion", TAU_SRC_MOTION))

    def qa3_fn(frames):
        return frame_qa_from_verdict(_calibrated_verdict(frames))

    # --- correction loop wiring ---
    def perceive_fn(frames):
        if csq_artifact is None:
            return perceive(frames, vlm_fn=vlm_fn, softness_fn=softness_fn,
                            holdfix_fn=hold_fixable_fraction)
        v = _calibrated_verdict(frames)
        try:                                    # hold_fixable drives the director's region_refill/ask_key choice
            hf = float(hold_fixable_fraction(frames))
        except Exception:
            hf = 0.0
        return dataclasses.replace(v, hold_fixable=hf)

    def decide_fn(verdict, region, attempts):
        if use_director and reason_fn is not None:
            return decide(verdict, region, attempts, reason_fn=reason_fn)
        return decide_fixed(verdict, region, attempts)

    def refill_fn(frames, a, b, region):
        if not region.mask:
            return list(frames)                     # nothing hold-fixable -> NO-OP (let the loop escalate)
        fill = hold_copy(a, b, len(frames))         # anti-ghost source copies
        return composite_region(frames, fill, region)

    def escalate_fn(a, b):
        # AniSora endpoint-conditioned; no artist breakdown at the escalate rung,
        # so the start key stands in as the placeholder mid.
        return anisora_gen(a, a, b, references=reference_frames_for_gen(spec))

    def split_fill_fn(a, m, b):
        return rife_engine(a, m) + rife_engine(m, b)

    def corrector(frames, a, b):
        return correct_inbetween(
            frames, a, b, perceive_fn=perceive_fn, localize_fn=localize_held_soft,
            decide_fn=decide_fn, refill_fn=refill_fn, escalate_fn=escalate_fn,
            askkey_fn=(askkey_fn or (lambda a, b: None)), split_fill_fn=split_fill_fn)

    return {"gap_fn": gap_score, "regime_fn": regime_fn, "interp_fn": interp_fn,
            "qa_fn": qa_fn, "softness_fn": softness_fn, "gen_fn": gen_fn,
            "breakdown_supply": breakdown_supply, "corrector": corrector,
            "qa3_fn": (qa3_fn if csq_artifact is not None else None),
            "qa_window": True}


def _assert_max_pixels_320():
    mp = os.environ.get("VISION_MAX_PIXELS_CHECK")
    if mp is None:
        print("[WARN] VISION_MAX_PIXELS_CHECK not set — cannot verify served max_pixels==320 (stale-copy gotcha)",
              file=sys.stderr)
    elif mp != "320":
        raise SystemExit(f"[ABORT] served max_pixels={mp!r}, expected 320 (stale-copy gotcha)")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--keys-dir", required=True, help="dir of ordered artist key PNGs")
    ap.add_argument("--spec", default=None, help="path to character_spec.json (optional)")
    ap.add_argument("--tau-hold", type=float, default=0.01)
    ap.add_argument("--tau-snap", type=float, default=0.20)
    args = ap.parse_args()
    _assert_max_pixels_320()
    # NOTE: load_frames + the real rife_engine/anisora_gen are imported from the
    # box adapters (.scratch/copilot/) at run time; wire them here.
    raise SystemExit("wire rife_engine/anisora_gen from .scratch/copilot, then run")


if __name__ == "__main__":
    raise SystemExit(main())
