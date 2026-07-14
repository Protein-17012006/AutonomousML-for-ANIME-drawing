"""Object facade for the correction application service."""
from __future__ import annotations

from dataclasses import dataclass

from inbetween_copilot.generate.correction import correct_inbetween
from inbetween_copilot.generate.ports import (
    AskKey,
    Decide,
    Escalate,
    Localize,
    Perceive,
    Refill,
    SplitFill,
)


@dataclass(frozen=True)
class CorrectInbetween:
    perceive_fn: Perceive
    localize_fn: Localize
    decide_fn: Decide
    refill_fn: Refill
    escalate_fn: Escalate
    askkey_fn: AskKey
    split_fill_fn: SplitFill
    max_rounds: int = 3

    def execute(self, frames, a, b):
        return correct_inbetween(
            frames, a, b,
            perceive_fn=self.perceive_fn,
            localize_fn=self.localize_fn,
            decide_fn=self.decide_fn,
            refill_fn=self.refill_fn,
            escalate_fn=self.escalate_fn,
            askkey_fn=self.askkey_fn,
            split_fill_fn=self.split_fill_fn,
            max_rounds=self.max_rounds,
        )
