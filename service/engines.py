"""Engine factories for the in-between co-pilot service.

stub_engines: fully deterministic, box-free (no GPU/network).
box_engines: wired to real model callables on the inference box (not importable here).
"""
from __future__ import annotations

import numpy as np

# re-export so `from service.engines import make_triage_fn` keeps working (the factory
# itself lives in inbetween_copilot/ so Task 10's pipeline/wiring.py can wire it too,
# without an upward import into service/). Cheap: factory.py's own imports are lazy.
from inbetween_copilot.triage.factory import make_triage_fn  # noqa: F401
from inbetween_copilot.triage.widegap import keys_from_gap
from service.engine_bundle import EngineBundle
from service.schemas import SessionCfg


def _stub_triage_fn(a, b, pp):
    """Deterministic triage for stub sessions: numpy-only, no network."""
    import dataclasses

    from inbetween_copilot.triage.brief import template_brief
    from inbetween_copilot.triage.widegap import classify_gap

    t = classify_gap(np.atleast_3d(np.asarray(a, np.uint8)),
                     np.atleast_3d(np.asarray(b, np.uint8)),
                     gap=pp.gap, regime=pp.regime, has_cut=False)
    return {**dataclasses.asdict(t), "brief": template_brief(t)}


def stub_engines(cfg: SessionCfg) -> EngineBundle:
    # gap_fn divides by 100.0 so that unit-spaced keys (e.g. 0,1,2) produce
    # gap = 0.01 < TAU_GATE (0.017) -> FILL; a large jump (e.g. 2->50) gives
    # gap = 0.48 > TAU_GATE -> needs_key.  /50 would give 0.02 > TAU_GATE
    # (all pairs gated out, n_autopass=0), which defeats the test intent.
    return EngineBundle(
        gap_fn=lambda a, b: float(np.mean(np.abs(np.asarray(b, float) - np.asarray(a, float)))) / 100.0,
        regime_fn=lambda a, b: "small",
        interp_fn=lambda route, a, b: [a, (a + b) // 2, b],
        # raw mid-frame engine for the decimate-vs-GT demo (overflow-safe mid)
        rife_engine=lambda a, b: [
            a, ((np.asarray(a, int) + np.asarray(b, int)) // 2).astype(np.uint8), b],
        qa_fn=lambda frames: False,
        softness_fn=lambda frames: 0.0,
        gen_fn=None,
        breakdown_supply=None,
        corrector=None,
        qa3_fn=None,
        triage_fn=_stub_triage_fn,
        # calibrated key budget (Task 10) — same keys_from_gap buckets triage.keys_suggested
        # uses, so stub keys_requested no longer diverges from the triage diagnosis.
        keys_needed_fn=lambda g: keys_from_gap(g),
        vlm_struct_fn=lambda frames: {
            "has_motion_error": False,
            "error_type": "none",
            "region": "none",
            "explanation": "stub: clean",
        },
        # explicit stub defaults (P1): the same fields box fills — no more silent
        # stub/box key divergence (csq_calibrator=None, vlm_status={}, qa_window=False).
        csq_calibrator=None,
        vlm_status={},
        qa_window=False,
    )


# Gate thresholds for box production (see vault 'Gate tau_snap Tighten'). Module-level
# so they import without box_engines' lazy torch dependency. tau_snap lowered 0.20->0.18:
# routes the magnitude-separable hard-motion leak (max step motion ~0.19) to snap_preserve
# (copy) instead of RIFE; zero measured over-gating (suite_smallgap n=60 + probe n=28,
# clean small max 0.15). w0052 (0.09) is a content-hard case, out of scope.
BOX_TAU_HOLD = 0.01
BOX_TAU_SNAP = 0.18


def box_engines(cfg: SessionCfg) -> EngineBundle:
    """Real RIFE + served-VLM wiring. ALL box imports are lazy (inside this function).
    Raises ImportError/ModuleNotFoundError/OSError if not on the inference box.
    """
    import os
    import sys

    # --- set VLM env (allow caller override) ---
    os.environ.setdefault("VISION_BASE_URL_CHECK", "http://100.71.161.102:8001/v1")
    os.environ.setdefault("VISION_MODEL_CHECK", "qwen3vl-anime")
    os.environ.setdefault("VISION_MAX_PIXELS_CHECK", "320")
    # stale-serve guard, now LIVE at engine-build time (audit 2026-07-02: it was only
    # reachable from a dead CLI stub). Aborts loudly if a caller exported a mismatched
    # max_pixels (train=320 vs serve gotcha, memory anime-finetune-32b-feasible).
    from inbetween_copilot.pipeline.wiring import _assert_max_pixels_320
    _assert_max_pixels_320()

    # --- lazy RIFE import (box-only; fails loudly off-box) ---
    sys.path.insert(0, "/home/long/Practical-RIFE")
    import torch
    from torch.nn import functional as F
    from train_log.RIFE_HDv3 import Model  # raises ImportError/ModuleNotFoundError off-box

    device = torch.device("cuda")
    torch.set_grad_enabled(False)
    rife_model = Model()
    rife_model.load_model("/home/long/Practical-RIFE/train_log", -1)
    rife_model.eval()
    rife_model.device()

    def rife_engine(a, b):
        """uint8 HxWx3 ndarray -> [a, mid, b] (uint8 HxWx3)."""
        def prep(x):
            return (torch.tensor(x.transpose(2, 0, 1)).to(device).float() / 255.).unsqueeze(0)
        i0, i1 = prep(a), prep(b)
        _, c, h, w = i0.shape
        ph = ((h - 1) // 64 + 1) * 64
        pw = ((w - 1) // 64 + 1) * 64
        i0 = F.pad(i0, (0, pw - w, 0, ph - h))
        i1 = F.pad(i1, (0, pw - w, 0, ph - h))
        mid = rife_model.inference(i0, i1)
        mid_np = (mid[0] * 255).byte().cpu().numpy().transpose(1, 2, 0)[:h, :w]
        return [a, mid_np, b]

    # --- served VLM fns (transport = service/box_vlm.py adapter; prompts live
    # beside the validated perception prompts in inbetween_copilot/qa/perception) ---
    from inbetween_copilot.qa.perception import BINARY_PROMPT as _BINARY_PROMPT
    from inbetween_copilot.qa.perception import PERCEPTION_PROMPT as _STRUCT_PROMPT
    from service.box_vlm import make_post_vlm

    VLM_URL = os.environ["VISION_BASE_URL_CHECK"].rstrip("/") + "/chat/completions"
    VLM_MODEL = os.environ["VISION_MODEL_CHECK"]
    _post_vlm, vlm_status = make_post_vlm(VLM_URL, VLM_MODEL)

    def vlm_fn(frames):
        """frames: list of uint8 HxWx3 ndarray. Returns {"has_motion_error": bool, "verdict_prob": float}."""
        raw = _post_vlm(_BINARY_PROMPT, frames)
        return {
            "has_motion_error": bool(raw.get("has_motion_error")),
            "verdict_prob": float(raw.get("verdict_prob", 0.5)),
        }

    def vlm_struct_fn(frames):
        """Structured VLM: returns full explanation dict for the explainability layer."""
        raw = _post_vlm(_STRUCT_PROMPT, frames)
        return {
            "has_motion_error": bool(raw.get("has_motion_error")),
            "error_type": str(raw.get("error_type", "none")),
            "region": str(raw.get("region", "none")),
            "explanation": str(raw.get("explanation", "")),
        }

    # --- CSQ artifact ---
    from inbetween_copilot.qa.csq.artifact import load_artifact
    art = load_artifact("inbetween_copilot/artifacts/csq_smallgap_v3.json")

    # --- AniSora placeholder (large-gap generator; out of slice-1.5 scope) ---
    # Real AniSora wiring is deferred: co-residency with the live VLM on 32GB VRAM
    # is not feasible in this slice (see copilot_correct.py escalate note).
    anisora_gen = lambda a, m, b, references=None: [a, m, b]

    # --- reason_fn (DeepSeek director) — the agentic brain on the LIVE path ---
    # make_reason_fn() reads DEEPSEEK_API_KEY/_MODEL/_BASE_URL from the ambient env
    # (deploy_box.sh does NOT sync .env — export the key in the shell that runs
    # box_start_service.sh). No key -> None -> decide_fixed (today's behaviour);
    # endpoint failure -> {} -> decide() falls back per round. Never crashes a run.
    from service.director_llm import make_ask_fn, make_reason_fn
    reason_fn = make_reason_fn()
    if reason_fn is None:
        print("[box_engines] DEEPSEEK_API_KEY not set — director runs the fixed "
              "ladder (decide_fixed), not the DeepSeek brain.",
              file=sys.stderr, flush=True)

    from inbetween_copilot.pipeline.wiring import build_real_callables
    # ask_fn: wide-gap diagnosis (ADR-0015) gets an LLM-written brief when
    # DEEPSEEK_API_KEY is set; make_ask_fn() -> None degrades to template-only.
    callables = build_real_callables(
        None,
        tau_hold=BOX_TAU_HOLD,
        tau_snap=BOX_TAU_SNAP,
        rife_engine=rife_engine,
        anisora_gen=anisora_gen,
        vlm_fn=vlm_fn,
        csq_artifact=art,
        reason_fn=reason_fn,
        ask_fn=make_ask_fn(),
    )
    # surface the calibrated abstain band so the UI dial can draw the measured pass/abstain/flag
    # zones (per-u-bin thresholds on p_error) — the trust instrument, not just a bare %.
    cal = art.calibrator
    return EngineBundle(
        **callables,
        vlm_struct_fn=vlm_struct_fn,
        rife_engine=rife_engine,    # raw [a, mid, b] for the decimate-vs-GT demo
        vlm_status=vlm_status,      # degraded-QA flag -> ResultEvent.qa_degraded
        csq_calibrator={
            "tau_pass": list(cal.tau_pass), "tau_flag": list(cal.tau_flag),
            "u_edges": list(cal.u_edges), "u_max": cal.u_max,
        },
    )


def resolve(name: str, cfg: SessionCfg) -> EngineBundle:
    """Map the request's `engines` field to an EngineBundle. The single place the
    stub|box choice is decoded (was duplicated in the session + demo routes)."""
    from fastapi import HTTPException   # lazy: importing service.engines never requires fastapi
    if name == "stub":
        return stub_engines(cfg)
    if name == "box":
        return box_engines(cfg)
    raise HTTPException(status_code=400, detail=f"Unknown engines: {name!r}")
