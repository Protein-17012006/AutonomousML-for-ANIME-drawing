"""Command dispatcher for applying correction actions."""
from __future__ import annotations

from dataclasses import dataclass

from inbetween_copilot.generate.models import CorrectionAction, CorrectionActionKind


@dataclass(frozen=True)
class CommandOutcome:
    frames: list
    keys_used: int = 0
    needs_key: bool = False


@dataclass(frozen=True)
class CorrectionCommands:
    refill_fn: object
    escalate_fn: object
    askkey_fn: object
    split_fill_fn: object

    def execute(self, action: CorrectionAction, frames, a, b) -> CommandOutcome:
        handlers = {
            CorrectionActionKind.REGION_REFILL: self._refill,
            CorrectionActionKind.ESCALATE_ENGINE: self._escalate,
            CorrectionActionKind.ASK_KEY: self._ask_key,
        }
        return handlers[action.kind](action, frames, a, b)

    def _refill(self, action, frames, a, b) -> CommandOutcome:
        return CommandOutcome(self.refill_fn(frames, a, b, action.region))

    def _escalate(self, action, frames, a, b) -> CommandOutcome:
        return CommandOutcome(self.escalate_fn(a, b))

    def _ask_key(self, action, frames, a, b) -> CommandOutcome:
        middle = self.askkey_fn(a, b)
        if middle is None:
            return CommandOutcome(frames, needs_key=True)
        return CommandOutcome(self.split_fill_fn(a, middle, b), keys_used=1)
