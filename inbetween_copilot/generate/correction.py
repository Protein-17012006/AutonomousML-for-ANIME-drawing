"""The bounded collaborative correction loop (pure orchestration).

perceive -> (clean? done) -> localize -> decide -> apply (region re-fill /
engine escalate / ask the artist for a key) -> re-QA, up to max_rounds. Ends
at the artist: `needs_key` when the artist declines a requested key,
`unresolved` when rounds are exhausted still-flagged. All engines/agents are
injected (mirrors benchmark.repair.cascade.repair_cut) -- no torch/cv2/net.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass
class CorrectionRound:
    action_kind: str
    region: object          # Region | None
    verdict: object         # QAVerdict (pre-action)
    u_delta: float = 0.0


@dataclass
class CorrectionResult:
    status: str             # "resolved" | "needs_key" | "unresolved"
    frames: list
    rounds: list
    keys_used: int
    final_verdict: object   # QAVerdict


def correct_inbetween(frames, a, b, *, perceive_fn, localize_fn, decide_fn,
                      refill_fn, escalate_fn, askkey_fn, split_fill_fn,
                      max_rounds: int = 3) -> CorrectionResult:
    cur = frames
    rounds: list = []
    keys_used = 0
    prev_u = None
    for _ in range(max_rounds):
        v = perceive_fn(cur)
        if prev_u is not None and rounds:
            rounds[-1].u_delta = float(getattr(v, "u", 0.0)) - prev_u
        if not v.has_error:
            return CorrectionResult("resolved", cur, rounds, keys_used, v)
        region = localize_fn(cur)
        action = decide_fn(v, region, rounds)
        rounds.append(CorrectionRound(action.kind, action.region, v))
        prev_u = float(getattr(v, "u", 0.0))
        if action.kind == "region_refill":
            cur = refill_fn(cur, a, b, action.region)
        elif action.kind == "escalate_engine":
            cur = escalate_fn(a, b)
        else:  # ask_key
            m = askkey_fn(a, b)
            if m is None:
                return CorrectionResult("needs_key", cur, rounds, keys_used, v)
            keys_used += 1
            cur = split_fill_fn(a, m, b)
    v = perceive_fn(cur)
    if prev_u is not None and rounds:
        rounds[-1].u_delta = float(getattr(v, "u", 0.0)) - prev_u
    status = "resolved" if not v.has_error else "unresolved"
    return CorrectionResult(status, cur, rounds, keys_used, v)
