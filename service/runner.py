"""Session runner: wraps run_copilot with on_pair streaming and input validation."""
from __future__ import annotations

from inbetween_copilot.pipeline.copilot import run_copilot, CopilotResult


# Keys the service layer adds to the engines dict that run_copilot does not accept.
_SERVICE_ONLY_KEYS = {"vlm_struct_fn", "rife_engine", "csq_calibrator"}


def run_session(keys, engines: dict, on_pair=None) -> CopilotResult:
    if len(keys) < 2:
        raise ValueError("need >= 2 keys")
    copilot_kwargs = {k: v for k, v in engines.items() if k not in _SERVICE_ONLY_KEYS}
    return run_copilot(keys, on_pair=on_pair, **copilot_kwargs)


def recompute_result(pairs) -> CopilotResult:
    """Rebuild a CopilotResult's aggregates from a (re-indexed, spliced) pairs list.

    Mirrors run_copilot's own counting so a post-splice result is identical to a
    full re-run's: pass -> n_autopass; abstain -> abstained; flag -> flagged unless
    its correction resolved (then n_corrected). needs_key pairs only add keys_requested.
    """
    flagged: list = []
    abstained: list = []
    n_autopass = 0
    n_corrected = 0
    for p in pairs:
        if p.action == "needs_key" or p.qa is None:
            continue
        status = p.qa.status
        resolved = getattr(p.correction, "status", None) == "resolved"
        if status == "pass":
            n_autopass += 1
        elif status == "abstain":
            abstained.append(p.index)
        elif status == "flag":
            if resolved:
                n_corrected += 1
            else:
                flagged.append(p.index)
    return CopilotResult(
        pairs=pairs,
        keys_requested_total=sum(p.keys_requested for p in pairs),
        flagged=flagged, n_autopass=n_autopass,
        n_corrected=n_corrected, abstained=abstained,
    )
