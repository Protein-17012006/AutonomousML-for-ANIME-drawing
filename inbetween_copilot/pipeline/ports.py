"""Outbound ports required by the framework-independent co-pilot workflow."""
from __future__ import annotations

from dataclasses import dataclass, fields
from typing import Callable


@dataclass
class CopilotPorts:
    """Typed replacement for the historical dictionary of callable engines."""

    gap_fn: Callable
    regime_fn: Callable
    interp_fn: Callable
    qa_fn: Callable
    softness_fn: Callable
    triage_fn: Callable
    keys_needed_fn: Callable
    gen_fn: "Callable | None" = None
    breakdown_supply: "Callable | None" = None
    corrector: "Callable | None" = None
    qa3_fn: "Callable | None" = None
    qa_window: bool = False

    def as_kwargs(self) -> dict:
        """Return exactly the keyword arguments accepted by ``run_copilot``."""
        return {item.name: getattr(self, item.name) for item in fields(CopilotPorts)}
