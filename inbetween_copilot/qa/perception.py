"""The perception agent (Qwen3-VL "eyes") of the correction loop.

Extends the binary detector to a structured verdict: does the in-between have
an error, what KIND, WHERE (a coarse 3x3 hint -- precise localization is the
deterministic localizer's job, the VLM is measured weak at it), and a one-line
why. `has_error` is the validated OR-union of the VLM verdict and the
reference-free softness signal, so the detector's recall and softness's
free recall both contribute. Fails safe: a dead/malformed VLM degrades to a
softness-only verdict, never raises.
"""
from __future__ import annotations

from dataclasses import dataclass

from inbetween_copilot.signals.prompt import _MOTION_PROMPT
from inbetween_copilot.qa.csq.channels import channel_scores
from inbetween_copilot.qa.csq.confidence import aggregate
from inbetween_copilot.qa.csq.perturb import flip_rates, perturb_views
from inbetween_copilot.qa.csq.verdict import Decision

_VALID_TYPES = {"ghost", "blur", "flicker", "morph", "identity_drift", "scene_break", "none"}
_VALID_HINTS = {"tl", "tc", "tr", "ml", "mc", "mr", "bl", "bc", "br", "whole", "none"}

PERCEPTION_PROMPT = (
    _MOTION_PROMPT
    + '\n\nAlso return "error_type" (one of: ghost, blur, flicker, morph, '
      'identity_drift, scene_break, none) and "region" (which third of the '
      'frame the worst error is in: tl, tc, tr, ml, mc, mr, bl, bc, br, or '
      '"whole" if it spans the frame, "none" if clean). '
      'JSON: {"has_motion_error": bool, "error_type": "...", "region": "...", '
      '"explanation": "<one sentence>"}')


@dataclass(frozen=True)
class QAVerdict:
    has_error: bool
    err_type: str
    region_hint: str
    explanation: str
    softness: float
    hold_fixable: float = 0.0
    decision: str = "flag"
    p_error: float = 1.0
    u: float = 0.0


def perceive(frames, *, vlm_fn, softness_fn, holdfix_fn=None,
             tau_soft: float = 0.15) -> QAVerdict:
    soft = float(softness_fn(frames))
    try:
        hf = float(holdfix_fn(frames)) if holdfix_fn is not None else 0.0
    except Exception:
        hf = 0.0
    try:
        raw = vlm_fn(frames) or {}
        vlm_err = bool(raw.get("has_motion_error"))
        err_type = raw.get("error_type", "none")
        err_type = err_type if err_type in _VALID_TYPES else "blur"
        hint = raw.get("region", "none")
        hint = hint if hint in _VALID_HINTS else "none"
        expl = str(raw.get("explanation", ""))
    except Exception:
        vlm_err, err_type, hint, expl = False, "blur", "whole", "vlm_unavailable"
    has_error = vlm_err or (soft > tau_soft)
    if has_error and err_type == "none":
        err_type = "blur"          # a softness-only flag is a soft/blur ghost
    decision = "flag" if has_error else "pass"
    return QAVerdict(has_error=has_error, err_type=err_type, region_hint=hint,
                     explanation=expl, softness=soft, hold_fixable=hf,
                     decision=decision, p_error=1.0 if has_error else 0.0, u=0.0)


def perceive_calibrated(frames, *, channel_fns, base_auc, calibrator,
                        transforms=None, k: int = 4, lam: float = 0.5,
                        stillness_fn=None, tau_still: float = 0.6,
                        source_motion_fn=None, tau_motion: float = 0.017) -> QAVerdict:
    scores = channel_scores(frames, channel_fns=channel_fns)
    views = perturb_views(frames, k=k, transforms=transforms)
    fr = flip_rates(frames, views, channel_fns=channel_fns)
    s, u = aggregate(scores, fr, base_auc=base_auc, lam=lam)
    decision = calibrator.decide(s, u)
    err_type = "blur"
    # Anti-Goodhart OR-guard (§5h): a static-hold step-function never auto-passes.
    # Deterministic, 0-FP on clean/legit-holds, so it only ever upgrades pass->flag.
    if stillness_fn is not None and decision == Decision.PASS:
        try:
            if float(stillness_fn(frames)) > tau_still:
                decision = Decision.FLAG
                err_type = "frozen_hold"
        except Exception:
            pass
    # Recall guard (§5n): a high-source-motion window can't be verified reference-free
    # (corr(src_motion, recon_psnr) = -0.81) -> never auto-pass, route to human (abstain).
    if source_motion_fn is not None and decision == Decision.PASS:
        try:
            if float(source_motion_fn(frames)) > tau_motion:
                decision = Decision.ABSTAIN
        except Exception:
            pass
    has_error = (decision != "pass")
    return QAVerdict(has_error=has_error, err_type=err_type if has_error else "none",
                     region_hint="whole" if has_error else "none", explanation="",
                     softness=s, hold_fixable=0.0, decision=str(decision.value),
                     p_error=calibrator.p_error(s), u=u)
