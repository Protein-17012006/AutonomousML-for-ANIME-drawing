"""The in-between co-pilot loop (dependency-injected, pure orchestration).

For each consecutive artist key-pair: the interpolable gate decides FILL vs
NEEDS_KEY; fillable pairs route to the cadence-preserving engine and are
self-QA'd; large-gap pairs request a breakdown key (or, if one is supplied,
are generated and self-QA'd). A flagged in-between optionally enters the
collaborative correction loop (injected `corrector`). All generation/detection
is injected -- this module has no torch/cv2/network.
"""
from __future__ import annotations

from inbetween_copilot.domain.states import (CorrectionStatus, PairAction,
                                              PlanAction, QAStatus, Route)
from inbetween_copilot.pipeline.plan import build_key_plan, TAU_GATE
from inbetween_copilot.pipeline.models import CopilotCfg, CopilotResult, PairResult
from inbetween_copilot.pipeline.route import choose_route
from inbetween_copilot.qa.gate import frame_qa, FrameQA
from inbetween_copilot.qa.window import windows_for_run


def _qa_for(frames, qa_fn, softness_fn, qa3_fn, tau_soft):
    """The calibrated 3-state self-QA (qa3_fn) when wired, else the binary OR-union.
    Keeping the binary as fallback is the CSQ deployment-swap contract (CSQ Design §5d)."""
    if qa3_fn is not None:
        return qa3_fn(frames)
    return frame_qa(qa_fn(frames), softness_fn(frames), tau_soft=tau_soft)


def aggregate_result(pairs) -> CopilotResult:
    """Derive a CopilotResult's aggregates from a finished pairs list — the ONE
    place the pass/abstain/flag/corrected tally lives (P6, 2026-07-08). Used by
    run_copilot at the end of PASS 2 and by service.sessions.runner.recompute_result after
    a draw-key splice, which used to mirror this logic by hand."""
    flagged: list = []
    abstained: list = []
    n_autopass = 0
    n_corrected = 0
    for p in pairs:
        if p.action == PairAction.NEEDS_KEY or p.qa is None:
            continue
        resolved = getattr(p.correction, "status", None) == CorrectionStatus.RESOLVED
        if p.qa.status == QAStatus.PASS:
            n_autopass += 1
        elif p.qa.status == QAStatus.ABSTAIN:
            abstained.append(p.index)
        elif p.qa.status == QAStatus.FLAG:
            if resolved:
                n_corrected += 1
            else:
                flagged.append(p.index)
    return CopilotResult(
        pairs=pairs,
        keys_requested_total=sum(p.keys_requested for p in pairs),
        flagged=flagged, n_autopass=n_autopass,
        n_corrected=n_corrected, abstained=abstained,
    )


def run_copilot(keys, *, gap_fn, regime_fn, interp_fn, qa_fn, softness_fn,
                gen_fn=None, breakdown_supply=None, corrector=None, qa3_fn=None,
                triage_fn=None, keys_needed_fn=None,
                on_pair=None, qa_window=False,
                cfg: CopilotCfg | None = None) -> CopilotResult:
    if len(keys) < 2:
        raise ValueError("run_copilot needs >= 2 keys")
    cfg = cfg or CopilotCfg(tau_gate=TAU_GATE)
    gaps = [gap_fn(keys[i], keys[i + 1]) for i in range(len(keys) - 1)]
    regimes = [regime_fn(keys[i], keys[i + 1]) for i in range(len(keys) - 1)]
    plan = build_key_plan(gaps, regimes, tau_gate=cfg.tau_gate, keys_needed_fn=keys_needed_fn)

    # --- PASS 1: interpolate / generate every pair; defer QA so neighbour mids
    # are available for the centered window. prelim is in plan order. ---
    prelim: list = []          # (pp, action, route, frames|None)
    filled: list = []          # (pair_index, [a, mid, b]) for windowing
    for pp in plan.pairs:
        a, b = keys[pp.index], keys[pp.index + 1]
        if pp.action == PlanAction.FILL:
            route = choose_route(pp.regime)
            frames = interp_fn(route, a, b)
            prelim.append((pp, PairAction.FILLED, route, frames))
            filled.append((pp.index, frames))
        else:  # needs_key
            m = breakdown_supply(a, b) if breakdown_supply is not None else None
            if m is not None and gen_fn is not None:
                frames = gen_fn(a, m, b)
                prelim.append((pp, PairAction.GENERATED, Route.GENERATIVE, frames))
                filled.append((pp.index, frames))
            else:
                prelim.append((pp, PairAction.NEEDS_KEY, None, None))

    windows = windows_for_run(filled) if qa_window else {}

    # --- PASS 2: QA on the (windowed or triplet) input; run the correction hook.
    # Aggregates are derived AFTER the loop by aggregate_result (P6). ---
    pairs: list = []
    for pp, action, route, frames in prelim:
        if action == PairAction.NEEDS_KEY:
            a, b = keys[pp.index], keys[pp.index + 1]
            tri = triage_fn(a, b, pp) if triage_fn is not None else None
            n_keys = (tri["keys_suggested"] if isinstance(tri, dict)
                      and "keys_suggested" in tri else pp.keys_to_request)
            pairs.append(PairResult(pp.index, PairAction.NEEDS_KEY, None, None, None,
                                    n_keys, triage=tri, regime=pp.regime))
            if on_pair is not None:
                on_pair(pairs[-1])
            continue
        a, b = keys[pp.index], keys[pp.index + 1]
        qa_input = windows.get(pp.index, frames) if qa_window else frames
        qa = _qa_for(qa_input, qa_fn, softness_fn, qa3_fn, cfg.tau_soft)
        pair = PairResult(
            pp.index, action, route, frames, qa, 0,
            regime=pp.regime,
        )  # pair.frames = triplet
        if qa.status == QAStatus.FLAG and corrector is not None:
            corr = corrector(pair.frames, a, b)          # corrector on the TRIPLET
            pair.correction = corr
            pair.frames = corr.frames
        pairs.append(pair)
        if on_pair is not None:
            on_pair(pairs[-1])

    return aggregate_result(pairs)
