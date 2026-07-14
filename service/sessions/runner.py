"""Session application runner: wraps run_copilot with pair-event callbacks."""
from __future__ import annotations

from inbetween_copilot.pipeline.copilot import aggregate_result
from inbetween_copilot.pipeline.models import CopilotResult
from inbetween_copilot.pipeline.ports import CopilotPorts
from inbetween_copilot.pipeline.service import RunCopilot


def run_session(keys, engines: CopilotPorts, on_pair=None) -> CopilotResult:
    if len(keys) < 2:
        raise ValueError("need >= 2 keys")
    return RunCopilot(engines).execute(keys, on_pair=on_pair)


def recompute_result(pairs) -> CopilotResult:
    """Rebuild a CopilotResult's aggregates from a (re-indexed, spliced) pairs list.
    Same tally as a full re-run BY CONSTRUCTION: both call copilot.aggregate_result
    (P6, 2026-07-08 — this used to mirror run_copilot's counting by hand)."""
    return aggregate_result(pairs)
