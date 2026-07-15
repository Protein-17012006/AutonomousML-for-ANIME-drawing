"""Infrastructure engine factories for the in-between co-pilot service.

stub_engines: fully deterministic, box-free (no GPU/network).
box_engines: wired to real model callables on the inference box (not importable here).
"""
from __future__ import annotations

import dataclasses
import threading

import numpy as np

# re-export so `from service.infrastructure.engines import make_triage_fn` keeps working (the factory
# itself lives in inbetween_copilot/ so Task 10's pipeline/wiring.py can wire it too,
# without an upward import into service/). Cheap: factory.py's own imports are lazy.
from inbetween_copilot.triage.factory import make_triage_fn  # noqa: F401
from inbetween_copilot.triage.widegap import keys_from_gap
from service.core.config import BoxSettings, ConfigurationError
from service.core.errors import UnknownEngine
from service.infrastructure.engine_bundle import EngineBundle


def _stub_triage_fn(a, b, pp):
    """Deterministic triage for stub sessions: numpy-only, no network."""
    import dataclasses

    from inbetween_copilot.triage.brief import template_brief
    from inbetween_copilot.triage.widegap import classify_gap

    t = classify_gap(np.atleast_3d(np.asarray(a, np.uint8)),
                     np.atleast_3d(np.asarray(b, np.uint8)),
                     gap=pp.gap, regime=pp.regime, has_cut=False)
    return {**dataclasses.asdict(t), "brief": template_brief(t)}


def stub_engines() -> EngineBundle:
    # gap_fn divides by 100.0 so that unit-spaced keys (e.g. 0,1,2) produce
    # gap = 0.01 < TAU_GATE (0.017) -> FILL; a large jump (e.g. 2->50) gives
    # gap = 0.48 > TAU_GATE -> needs_key.  /50 would give 0.02 > TAU_GATE
    # (all pairs gated out, n_autopass=0), which defeats the test intent.
    def midpoint(a, b):
        """Average uint8 values without wrapping before the division."""
        wide = (np.asarray(a, dtype=np.int32) + np.asarray(b, dtype=np.int32)) // 2
        mid = wide.astype(np.uint8)
        return mid.item() if mid.ndim == 0 else mid

    return EngineBundle(
        gap_fn=lambda a, b: float(np.mean(np.abs(np.asarray(b, float) - np.asarray(a, float)))) / 100.0,
        regime_fn=lambda a, b: "small",
        interp_fn=lambda route, a, b: [a, midpoint(a, b), b],
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


@dataclasses.dataclass(frozen=True)
class BoxRuntime:
    """Process-scoped heavyweight model assets.

    Bundles remain per-run (including their mutable VLM degraded status), while
    the CUDA-backed RIFE model is loaded exactly once and safely shared.
    """

    rife_engine: object
    rife_config: tuple[str, str, str] | None = None


def _rife_config(settings: BoxSettings) -> tuple[str, str, str]:
    return (
        str(settings.rife_root),
        str(settings.rife_model_dir),
        settings.rife_device,
    )


def _build_box_runtime(settings: BoxSettings | None = None) -> BoxRuntime:
    """Load RIFE lazily on the inference box and serialize model inference."""
    import sys

    settings = settings or BoxSettings.from_env()
    module_path = settings.rife_root / "train_log" / "RIFE_HDv3.py"
    if not settings.rife_root.is_dir():
        raise ConfigurationError(
            f"COPILOT_RIFE_ROOT is not a directory: {settings.rife_root}"
        )
    if not module_path.is_file():
        raise ConfigurationError(
            "COPILOT_RIFE_ROOT must contain train_log/RIFE_HDv3.py; "
            f"missing {module_path}"
        )
    if not settings.rife_model_dir.is_dir():
        raise ConfigurationError(
            f"COPILOT_RIFE_MODEL_DIR is not a directory: {settings.rife_model_dir}"
        )

    rife_root = str(settings.rife_root)
    if rife_root not in sys.path:
        sys.path.insert(0, rife_root)
    import torch
    from torch.nn import functional as F
    from train_log.RIFE_HDv3 import Model

    try:
        device = torch.device(settings.rife_device)
    except (RuntimeError, ValueError) as exc:
        raise ConfigurationError(
            f"COPILOT_RIFE_DEVICE is invalid: {settings.rife_device!r}"
        ) from exc
    if device.type == "cuda" and not torch.cuda.is_available():
        raise RuntimeError(
            f"COPILOT_RIFE_DEVICE={settings.rife_device!r} requires CUDA, "
            "but torch.cuda.is_available() is false"
        )

    rife_model = Model()
    rife_model.load_model(str(settings.rife_model_dir), -1)
    rife_model.eval()
    try:
        rife_model.flownet.to(device)
    except AttributeError as exc:
        raise RuntimeError(
            "Configured RIFE model does not expose flownet for device placement"
        ) from exc
    inference_lock = threading.Lock()

    def rife_engine(a, b):
        """uint8 HxWx3 ndarray -> [a, mid, b] (uint8 HxWx3)."""
        def prep(x):
            return (torch.tensor(x.transpose(2, 0, 1)).to(device).float() / 255.).unsqueeze(0)

        # Review and demo can call the shared model outside the session admission
        # controller, so the model itself must remain concurrency-safe.
        with inference_lock, torch.inference_mode():
            i0, i1 = prep(a), prep(b)
            _, _c, h, w = i0.shape
            ph = ((h - 1) // 64 + 1) * 64
            pw = ((w - 1) // 64 + 1) * 64
            i0 = F.pad(i0, (0, pw - w, 0, ph - h))
            i1 = F.pad(i1, (0, pw - w, 0, ph - h))
            mid = rife_model.inference(i0, i1)
            mid_np = (mid[0] * 255).byte().cpu().numpy().transpose(1, 2, 0)[:h, :w]
        return [a, mid_np, b]

    return BoxRuntime(
        rife_engine=rife_engine,
        rife_config=_rife_config(settings),
    )


_BOX_RUNTIME: BoxRuntime | None = None
_BOX_RUNTIME_LOCK = threading.Lock()


def _get_box_runtime(settings: BoxSettings | None = None) -> BoxRuntime:
    """Race-safe singleton; concurrent first requests cannot double-load CUDA."""
    global _BOX_RUNTIME
    settings = settings or BoxSettings.from_env()
    if _BOX_RUNTIME is None:
        with _BOX_RUNTIME_LOCK:
            if _BOX_RUNTIME is None:
                _BOX_RUNTIME = _build_box_runtime(settings)
    if (_BOX_RUNTIME.rife_config is not None
            and _BOX_RUNTIME.rife_config != _rife_config(settings)):
        raise ConfigurationError(
            "RIFE settings changed after the process runtime was initialized; "
            "restart the service to apply them"
        )
    return _BOX_RUNTIME


def box_engines() -> EngineBundle:
    """Real RIFE + served-VLM wiring. ALL box imports are lazy (inside this function).
    Raises ImportError/ModuleNotFoundError/OSError if not on the inference box.
    """
    import sys

    settings = BoxSettings.from_env()
    if not settings.csq_artifact_path.is_file():
        raise ConfigurationError(
            "COPILOT_CSQ_ARTIFACT_PATH is not a file: "
            f"{settings.csq_artifact_path}"
        )

    # --- process-scoped RIFE runtime (box-only; fails loudly off-box) ---
    rife_engine = _get_box_runtime(settings).rife_engine

    # --- served VLM fns (transport = service/box_vlm.py adapter; prompts live
    # beside the validated perception prompts in inbetween_copilot/qa/perception) ---
    from inbetween_copilot.qa.perception import BINARY_PROMPT as _BINARY_PROMPT
    from inbetween_copilot.qa.perception import PERCEPTION_PROMPT as _STRUCT_PROMPT
    from service.infrastructure.box_vlm import make_post_vlm

    VLM_URL = settings.vlm_base_url + "/chat/completions"
    VLM_MODEL = settings.vlm_model
    _post_vlm, vlm_status = make_post_vlm(VLM_URL, VLM_MODEL)

    def vlm_fn(frames):
        """frames: list of uint8 HxWx3 ndarray. Returns {"has_motion_error": bool, "verdict_prob": float}."""
        raw = _post_vlm(_BINARY_PROMPT, frames)
        try:
            probability = float(raw.get("verdict_prob"))
            valid_probability = (
                not isinstance(raw.get("verdict_prob"), bool)
                and np.isfinite(probability)
                and 0.0 <= probability <= 1.0
            )
        except (AttributeError, TypeError, ValueError):
            valid_probability = False
        if (not raw or not isinstance(raw.get("has_motion_error"), bool)
                or not valid_probability):
            # Preserve channel absence. Coercing {} to False/0.5 previously let
            # a transport outage contribute a clean VLM vote and auto-pass.
            vlm_status["degraded"] = True
            return {"available": False}
        return {
            "available": True,
            "has_motion_error": bool(raw.get("has_motion_error")),
            "verdict_prob": probability,
        }

    def vlm_struct_fn(frames):
        """Structured VLM: returns full explanation dict for the explainability layer."""
        raw = _post_vlm(_STRUCT_PROMPT, frames)
        if not raw or not isinstance(raw.get("has_motion_error"), bool):
            vlm_status["degraded"] = True
            return {
                "available": False,
                "has_motion_error": False,
                "error_type": "none",
                "region": "none",
                "explanation": "vlm_unavailable",
            }
        return {
            "available": True,
            "has_motion_error": bool(raw.get("has_motion_error")),
            "error_type": str(raw.get("error_type", "none")),
            "region": str(raw.get("region", "none")),
            "explanation": str(raw.get("explanation", "")),
        }

    # --- CSQ artifact ---
    from inbetween_copilot.infrastructure.artifact_json import CSQArtifactJsonStore
    art = CSQArtifactJsonStore().load(str(settings.csq_artifact_path))

    # --- AniSora placeholder (large-gap generator; out of slice-1.5 scope) ---
    # Real AniSora wiring is deferred: co-residency with the live VLM on 32GB VRAM
    # is not feasible in this slice (see copilot_correct.py escalate note).
    anisora_gen = lambda a, m, b, references=None: [a, m, b]

    # --- reason_fn (DeepSeek director) — the agentic brain on the LIVE path ---
    # make_reason_fn() reads DEEPSEEK_API_KEY/_MODEL/_BASE_URL from the ambient env
    # (deploy_box.sh does NOT sync .env — export the key in the shell that runs
    # box_start_service.sh). No key -> None -> decide_fixed (today's behaviour);
    # endpoint failure -> {} -> decide() falls back per round. Never crashes a run.
    from service.infrastructure.director_llm import make_ask_fn, make_reason_fn
    reason_fn = make_reason_fn()
    if reason_fn is None:
        print("[box_engines] DEEPSEEK_API_KEY not set — director runs the fixed "
              "ladder (decide_fixed), not the DeepSeek brain.",
              file=sys.stderr, flush=True)

    from inbetween_copilot.composition import build_real_ports
    # ask_fn: wide-gap diagnosis (ADR-0015) gets an LLM-written brief when
    # DEEPSEEK_API_KEY is set; make_ask_fn() -> None degrades to template-only.
    ports = build_real_ports(
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
    return EngineBundle.from_ports(
        ports,
        vlm_struct_fn=vlm_struct_fn,
        rife_engine=rife_engine,    # raw [a, mid, b] for the decimate-vs-GT demo
        vlm_status=vlm_status,      # degraded-QA flag -> ResultEvent.qa_degraded
        csq_calibrator={
            "tau_pass": list(cal.tau_pass), "tau_flag": list(cal.tau_flag),
            "u_edges": list(cal.u_edges), "u_max": cal.u_max,
        },
    )


def resolve(name: str) -> EngineBundle:
    """Map the request's `engines` field to an EngineBundle. The single place the
    stub|box choice is decoded (was duplicated in the session + demo routes)."""
    if name == "stub":
        return stub_engines()
    if name == "box":
        return box_engines()
    raise UnknownEngine(f"Unknown engines: {name!r}")
