"""The typed message protocol. Types only — no behaviour, no I/O.

`refused` means the agent declined the request AS ASKED; its `payload` may still
carry what it was willing to provide. That is how the Triage agent returns a class
and a brief while refusing to supply an uncalibrated key count.
"""
from __future__ import annotations

from dataclasses import dataclass, field

MAX_PLAN_STEPS = 5
MAX_TRANSCRIPT_ENTRIES = 64

STATUSES = ("ok", "refused", "queued", "rejected", "error")
ENTRY_KINDS = ("ask", "reply", "refuse", "queue", "error")
KINDS = ("agent", "tool")


@dataclass(frozen=True)
class Step:
    id: int
    target: str
    kind: str                       # "agent" | "tool"
    ask: str = ""
    args: dict = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.kind not in KINDS:
            raise ValueError(f"unknown step kind {self.kind!r}")


@dataclass(frozen=True)
class Plan:
    goal: str
    steps: tuple = ()
    reason: str | None = None

    def is_actionable(self) -> bool:
        return bool(self.steps)


@dataclass(frozen=True)
class StepResult:
    step_id: int
    target: str
    kind: str
    status: str
    says: str = ""
    payload: dict = field(default_factory=dict)
    ms: int = 0
    # An agent may route work it refuses to another agent. Validated in dispatch,
    # not here: this module is types only.
    handoff: dict | None = None

    def __post_init__(self) -> None:
        if self.status not in STATUSES:
            raise ValueError(f"unknown step status {self.status!r}")


@dataclass(frozen=True)
class TranscriptEntry:
    seq: int
    frm: str
    to: str
    kind: str
    text: str
    data: dict = field(default_factory=dict)
    ms: int = 0
    ts: float = 0.0

    def as_dict(self) -> dict:
        return {"seq": self.seq, "frm": self.frm, "to": self.to,
                "kind": self.kind, "text": self.text, "data": dict(self.data),
                "ms": self.ms, "ts": self.ts}
