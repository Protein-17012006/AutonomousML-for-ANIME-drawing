"""Session runner: wraps run_copilot with on_pair streaming and input validation."""
from __future__ import annotations

from inbetween_copilot.pipeline.copilot import aggregate_result, run_copilot, CopilotResult
from service.engine_bundle import EngineBundle


def run_session(keys, engines: EngineBundle, on_pair=None) -> CopilotResult:
    if len(keys) < 2:
        raise ValueError("need >= 2 keys")
    return run_copilot(keys, on_pair=on_pair, **engines.copilot_kwargs())


def recompute_result(pairs) -> CopilotResult:
    """Rebuild a CopilotResult's aggregates from a (re-indexed, spliced) pairs list.
    Same tally as a full re-run BY CONSTRUCTION: both call copilot.aggregate_result
    (P6, 2026-07-08 — this used to mirror run_copilot's counting by hand)."""
    return aggregate_result(pairs)
