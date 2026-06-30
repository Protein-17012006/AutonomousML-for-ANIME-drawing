"""The director agent (DeepSeek "brain") of the correction loop.

Reads the perception verdict + attempt history and CHOOSES the next fix:
re-fill the localized region, escalate the engine on the whole pair, or ask
the artist for a key. `decide` is the agent; `decide_fixed` is the
deterministic 3-rung ladder it must be measured against (an agent is only
worth it if it beats the fixed ladder). The agent may short-circuit -- e.g.
a whole-frame morph straight to ask_key -- which the fixed ladder cannot.
Fails safe: bad/again output falls back to the fixed ladder for that round.
"""
from __future__ import annotations

from dataclasses import dataclass

_KINDS = {"region_refill", "escalate_engine", "ask_key"}
_METHODS = {"hold_copy", "alt_engine"}


@dataclass(frozen=True)
class CorrectionAction:
    kind: str
    region: object          # Region | None
    method: str
    reason: str


def decide_fixed(verdict, region, attempts, *, tau_holdfix: float = 0.05) -> CorrectionAction:
    if getattr(verdict, "decision", None) == "abstain" and attempts:
        return CorrectionAction("ask_key", None, "", "abstain-after-fix")
    n = len(attempts)
    if n == 0:
        if verdict.hold_fixable > tau_holdfix:
            return CorrectionAction("region_refill", region, "hold_copy", "fixed:round0")
        return CorrectionAction("ask_key", None, "", "fixed:round0:not-hold-fixable")
    if n == 1:
        return CorrectionAction("escalate_engine", None, "", "fixed:round1")
    return CorrectionAction("ask_key", None, "", "fixed:round2")


def _director_prompt(verdict, attempts) -> str:
    return (
        "A self-QA agent flagged an interpolated anime in-between.\n"
        f"verdict: has_error={verdict.has_error} type={verdict.err_type} "
        f"region_hint={verdict.region_hint} softness={verdict.softness:.3f} "
        f"hold_fixable={verdict.hold_fixable:.2f}\n"
        f"explanation: {verdict.explanation}\n"
        f"attempts so far: {[a.action_kind for a in attempts]}\n"
        "Choose ONE next action to fix it: region_refill (re-fill only the bad "
        "region; cheap; good for a localized ghost), escalate_engine (redraw the "
        "whole pair with the stronger generator; for frame-wide breakdowns), or "
        "ask_key (ask the artist to draw one breakdown key; for gaps too large "
        "to fix).\n"
        "If hold_fixable is near 0, region_refill cannot help (nothing is hold-fixable) — "
        "prefer ask_key.\n"
        'Return JSON: {"action": "region_refill|escalate_engine|ask_key", '
        '"method": "hold_copy|alt_engine", "reason": "<short>"}')


def decide(verdict, region, attempts, *, reason_fn,
           tau_holdfix: float = 0.05) -> CorrectionAction:
    if getattr(verdict, "decision", None) == "abstain" and attempts:
        return CorrectionAction("ask_key", None, "", "abstain-after-fix")
    try:
        raw = reason_fn(_director_prompt(verdict, attempts)) or {}
        kind = raw.get("action")
        if kind not in _KINDS:
            return decide_fixed(verdict, region, attempts, tau_holdfix=tau_holdfix)
        if kind == "region_refill":
            # Safety override: if nothing is hold-fixable, a region_refill will no-op
            if verdict.hold_fixable <= tau_holdfix:
                return CorrectionAction("ask_key", None, "", "override:not-hold-fixable")
            method = raw.get("method", "hold_copy")
            method = method if method in _METHODS else "hold_copy"
            return CorrectionAction(kind, region, method, "director:" + str(raw.get("reason", "")))
        return CorrectionAction(kind, None, "", "director:" + str(raw.get("reason", "")))
    except Exception:
        return decide_fixed(verdict, region, attempts, tau_holdfix=tau_holdfix)
