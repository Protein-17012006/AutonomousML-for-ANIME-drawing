"""The bounded collaborative correction loop (pure orchestration).

perceive -> (clean? done) -> localize -> decide -> apply (region re-fill /
engine escalate / ask the artist for a key) -> re-QA, up to max_rounds. Ends
at the artist: `needs_key` when the artist declines a requested key,
`unresolved` when rounds are exhausted still-flagged. All engines/agents are
injected (mirrors benchmark.repair.cascade.repair_cut) -- no torch/cv2/net.
"""
from __future__ import annotations

from inbetween_copilot.generate.commands import CorrectionCommands
from inbetween_copilot.generate.models import CorrectionResult, CorrectionRound
from inbetween_copilot.pipeline.states import CorrectionStatus


def correct_inbetween(frames, a, b, *, perceive_fn, localize_fn, decide_fn,
                      refill_fn, escalate_fn, askkey_fn, split_fill_fn,
                      max_rounds: int = 3) -> CorrectionResult:
    cur = frames
    rounds: list = []
    keys_used = 0
    prev_u = None
    commands = CorrectionCommands(refill_fn, escalate_fn, askkey_fn, split_fill_fn)
    for _ in range(max_rounds):
        v = perceive_fn(cur)
        if prev_u is not None and rounds:
            rounds[-1].u_delta = float(getattr(v, "u", 0.0)) - prev_u
        if not v.has_error:
            return CorrectionResult(CorrectionStatus.RESOLVED, cur, rounds, keys_used, v)
        region = localize_fn(cur)
        action = decide_fn(v, region, rounds)
        rounds.append(CorrectionRound(action.kind, action.region, v,
                                      reason=getattr(action, "reason", "")))
        prev_u = float(getattr(v, "u", 0.0))
        outcome = commands.execute(action, cur, a, b)
        if outcome.needs_key:
            return CorrectionResult(CorrectionStatus.NEEDS_KEY, cur, rounds, keys_used, v)
        keys_used += outcome.keys_used
        cur = outcome.frames
    v = perceive_fn(cur)
    if prev_u is not None and rounds:
        rounds[-1].u_delta = float(getattr(v, "u", 0.0)) - prev_u
    status = CorrectionStatus.RESOLVED if not v.has_error else CorrectionStatus.UNRESOLVED
    return CorrectionResult(status, cur, rounds, keys_used, v)
