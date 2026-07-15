"""Build the bounded correction capability from injected engines and policies."""
from __future__ import annotations

from typing import Callable

from inbetween_copilot.generate.correct import composite_region, hold_copy
from inbetween_copilot.generate.director import decide, decide_fixed
from inbetween_copilot.generate.localize import localize_held_soft
from inbetween_copilot.generate.service import CorrectInbetween


def build_corrector(
    *,
    perceive_fn: Callable,
    rife_engine: Callable,
    anisora_gen: Callable,
    references: list,
    reason_fn=None,
    askkey_fn=None,
    use_director: bool = True,
):
    def decide_fn(verdict, region, attempts):
        if use_director and reason_fn is not None:
            return decide(verdict, region, attempts, reason_fn=reason_fn)
        return decide_fixed(verdict, region, attempts)

    def refill_fn(frames, a, b, region):
        if not region.mask:
            return list(frames)
        return composite_region(frames, hold_copy(a, b, len(frames)), region)

    def escalate_fn(a, b):
        return anisora_gen(a, a, b, references=references)

    def split_fill_fn(a, middle, b):
        return rife_engine(a, middle) + rife_engine(middle, b)

    def decline_key(a, b):
        return None

    return CorrectInbetween(
        perceive_fn=perceive_fn,
        localize_fn=localize_held_soft,
        decide_fn=decide_fn,
        refill_fn=refill_fn,
        escalate_fn=escalate_fn,
        askkey_fn=askkey_fn or decline_key,
        split_fill_fn=split_fill_fn,
    ).execute
