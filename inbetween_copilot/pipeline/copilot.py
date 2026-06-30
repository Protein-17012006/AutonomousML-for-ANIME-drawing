"""The in-between co-pilot loop (dependency-injected, pure orchestration).

For each consecutive artist key-pair: the interpolable gate decides FILL vs
NEEDS_KEY; fillable pairs route to the cadence-preserving engine and are
self-QA'd; large-gap pairs request a breakdown key (or, if one is supplied,
are generated and self-QA'd). A flagged in-between optionally enters the
collaborative correction loop (injected `corrector`). All generation/detection
is injected -- this module has no torch/cv2/network.
"""
from __future__ import annotations

from dataclasses import dataclass

from inbetween_copilot.pipeline.plan import build_key_plan, TAU_GATE
from inbetween_copilot.pipeline.route import choose_route
from inbetween_copilot.qa.gate import frame_qa, FrameQA
from inbetween_copilot.qa.window import windows_for_run


def _qa_for(frames, qa_fn, softness_fn, qa3_fn, tau_soft):
    """The calibrated 3-state self-QA (qa3_fn) when wired, else the binary OR-union.
    Keeping the binary as fallback is the CSQ deployment-swap contract (CSQ Design §5d)."""
    if qa3_fn is not None:
        return qa3_fn(frames)
    return frame_qa(qa_fn(frames), softness_fn(frames), tau_soft=tau_soft)


@dataclass
class CopilotCfg:
    tau_gate: float = TAU_GATE   # recalibrated 0.18 -> 0.017 (see plan.TAU_GATE)
    tau_soft: float = 0.15


@dataclass
class PairResult:
    index: int
    action: str               # "filled" | "generated" | "needs_key"
    route: str | None
    frames: list | None
    qa: FrameQA | None
    keys_requested: int
    correction: object = None  # CorrectionResult | None


@dataclass
class CopilotResult:
    pairs: list
    keys_requested_total: int
    flagged: list
    n_autopass: int
    n_corrected: int = 0
    abstained: list = None     # indices the calibrated QA was unsure about -> artist review

    def __post_init__(self):
        if self.abstained is None:
            self.abstained = []


def run_copilot(keys, *, gap_fn, regime_fn, interp_fn, qa_fn, softness_fn,
                gen_fn=None, breakdown_supply=None, corrector=None, qa3_fn=None,
                on_pair=None, qa_window=False,
                cfg: CopilotCfg = CopilotCfg()) -> CopilotResult:
    if len(keys) < 2:
        raise ValueError("run_copilot needs >= 2 keys")
    gaps = [gap_fn(keys[i], keys[i + 1]) for i in range(len(keys) - 1)]
    regimes = [regime_fn(keys[i], keys[i + 1]) for i in range(len(keys) - 1)]
    plan = build_key_plan(gaps, regimes, tau_gate=cfg.tau_gate)

    # --- PASS 1: interpolate / generate every pair; defer QA so neighbour mids
    # are available for the centered window. prelim is in plan order. ---
    prelim: list = []          # (pp, action, route, frames|None)
    filled: list = []          # (pair_index, [a, mid, b]) for windowing
    for pp in plan.pairs:
        a, b = keys[pp.index], keys[pp.index + 1]
        if pp.action == "fill":
            route = choose_route(pp.regime)
            frames = interp_fn(route, a, b)
            prelim.append((pp, "filled", route, frames))
            filled.append((pp.index, frames))
        else:  # needs_key
            m = breakdown_supply(a, b) if breakdown_supply is not None else None
            if m is not None and gen_fn is not None:
                frames = gen_fn(a, m, b)
                prelim.append((pp, "generated", "generative", frames))
                filled.append((pp.index, frames))
            else:
                prelim.append((pp, "needs_key", None, None))

    windows = windows_for_run(filled) if qa_window else {}

    # --- PASS 2: QA on the (windowed or triplet) input; handle abstain/flag. ---
    pairs: list = []
    flagged: list = []
    abstained: list = []
    n_autopass = 0
    n_corrected = 0
    for pp, action, route, frames in prelim:
        if action == "needs_key":
            pairs.append(PairResult(pp.index, "needs_key", None, None, None,
                                    pp.keys_to_request))
            if on_pair is not None:
                on_pair(pairs[-1])
            continue
        a, b = keys[pp.index], keys[pp.index + 1]
        qa_input = windows.get(pp.index, frames) if qa_window else frames
        qa = _qa_for(qa_input, qa_fn, softness_fn, qa3_fn, cfg.tau_soft)
        pair = PairResult(pp.index, action, route, frames, qa, 0)   # pair.frames = triplet
        if qa.status == "abstain":
            abstained.append(pp.index)
        elif qa.status == "flag":
            if corrector is not None:
                corr = corrector(pair.frames, a, b)      # corrector on the TRIPLET
                pair.correction = corr
                pair.frames = corr.frames
                if corr.status == "resolved":
                    n_corrected += 1
                else:
                    flagged.append(pp.index)
            else:
                flagged.append(pp.index)
        else:
            n_autopass += 1
        pairs.append(pair)
        if on_pair is not None:
            on_pair(pairs[-1])

    return CopilotResult(pairs=pairs,
                         keys_requested_total=sum(p.keys_requested for p in pairs),
                         flagged=flagged, n_autopass=n_autopass,
                         n_corrected=n_corrected, abstained=abstained)
