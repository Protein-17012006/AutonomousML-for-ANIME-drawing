"""The single definition of the live/calibration CSQ channel bank and the (s, u)
it produces -- shared by the production path (run_copilot), the artifact fitter,
the suite freeze, and the campaign eval, so the channel construction is written
ONCE. VLM is a constant channel (computed once, flip_rate 0) faithful to the
Phase-1 calibration; softness/sharpness recompute per perturbed view. A
box-measured served-VLM flip-rate may be injected via `vlm_perturb_flip`."""
from __future__ import annotations

from inbetween_copilot.qa.csq.channels import channel_scores
from inbetween_copilot.qa.csq.confidence import aggregate
from inbetween_copilot.qa.csq.perturb import perturb_views, flip_rates
from inbetween_copilot.signals.softness import interp_softness
from inbetween_copilot.signals.sharpness import clip_score, SPATIAL_THRESH

TAU_SOFT = 0.15
TAU_SHARP_REL = 0.25      # soft_worst fires threshold (relative sharpness channel)


def standard_channel_fns(vlm_err: bool, *, tau_soft: float = TAU_SOFT,
                         vlm_score=None, sharp_mode: str = "absolute") -> dict:
    """The 3-channel bank. `vlm_score` (a continuous P(error), §5k) overrides the
    binary {0,1} VLM encoding when given: score=vlm_score, fires=vlm_score>0.5.
    `sharp_mode`: "absolute" = clip_score (LAP_REF-normalized, miscalibrates across
    shows); "relative" = interp_softness.soft_worst (interp-vs-source worst frame,
    content-independent — the §5m cross-show fix)."""
    if vlm_score is None:
        vlm_chan = (lambda f, _v=bool(vlm_err): (1.0 if _v else 0.0, _v))
    else:
        vlm_chan = (lambda f, _p=float(vlm_score): (_p, _p > 0.5))
    if sharp_mode == "relative":
        sharp_chan = (lambda f: ((sw := float(interp_softness(f)["soft_worst"]) if len(f) >= 2 else 0.0),
                                 sw > TAU_SHARP_REL))
    else:
        sharp_chan = (lambda f: ((cs := float(clip_score(f))), cs > SPATIAL_THRESH))
    return {
        "vlm": vlm_chan,
        "softness": lambda f: ((sm := float(interp_softness(f)["soft_mean"]) if len(f) >= 2 else 0.0),
                               sm > tau_soft),
        "sharpness": sharp_chan,
    }


def clip_su(frames, vlm_err: bool, *, base_auc, tau_soft: float = TAU_SOFT,
            k: int = 4, lam: float = 0.5, vlm_perturb_flip=None, vlm_score=None,
            sharp_mode: str = "absolute"):
    """(s, u) for a clip given its (cached/served) VLM verdict. `vlm_score` swaps the
    binary VLM channel for a continuous P(error); `sharp_mode` swaps the absolute
    sharpness channel for the content-relative one. If a box-measured served-VLM
    flip-rate is supplied it overrides the recomputed (constant) one."""
    fns = standard_channel_fns(vlm_err, tau_soft=tau_soft, vlm_score=vlm_score, sharp_mode=sharp_mode)
    fr = flip_rates(frames, perturb_views(frames, k=k), channel_fns=fns)
    if vlm_perturb_flip is not None:
        fr["vlm"] = float(vlm_perturb_flip)
    return aggregate(channel_scores(frames, channel_fns=fns), fr, base_auc=base_auc, lam=lam)
