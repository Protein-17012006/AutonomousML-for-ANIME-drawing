"""Object facade for the correction application service."""
from __future__ import annotations

from dataclasses import dataclass

from inbetween_copilot.generate.correction import correct_inbetween


@dataclass(frozen=True)
class CorrectInbetween:
    perceive_fn: object
    localize_fn: object
    decide_fn: object
    refill_fn: object
    escalate_fn: object
    askkey_fn: object
    split_fill_fn: object
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
