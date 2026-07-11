"""The typed outbound-engine contract (architecture review 2026-07-08, P1).

One bundle, two producers (`stub_engines` / `box_engines`), consumed by the
runner (copilot side) and the service layer (streaming / routes). Before this,
the contract was a plain dict with 16 magic string keys where stub and box
silently diverged (csq_calibrator/vlm_status/qa_window existed only on box) and
the service-only subset lived in a hand-synced string set (_SERVICE_ONLY_KEYS).
Now both producers MUST fill the same fields, and the copilot-vs-service split
is a method, not a convention.
"""
from __future__ import annotations

import dataclasses
from typing import Callable

# The fields run_copilot() accepts as kwargs — everything else is service-only.
_SERVICE_ONLY = ("rife_engine", "vlm_struct_fn", "csq_calibrator", "vlm_status")


@dataclasses.dataclass
class EngineBundle:
    # --- copilot-side (splatted into run_copilot via copilot_kwargs()) ---
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
    # --- service-only (never reach run_copilot) ---
    rife_engine: "Callable | None" = None      # raw [a, mid, b] (demo + smoothness x4)
    vlm_struct_fn: "Callable | None" = None    # explainability layer
    csq_calibrator: "dict | None" = None       # UI trust dial (box only)
    vlm_status: dict = dataclasses.field(default_factory=dict)  # degraded-QA flag

    def copilot_kwargs(self) -> dict:
        """Exactly the kwargs run_copilot accepts (was: dict-filter against a
        magic string set in service/runner.py)."""
        return {f.name: getattr(self, f.name)
                for f in dataclasses.fields(self) if f.name not in _SERVICE_ONLY}

    def override(self, **fields) -> "EngineBundle":
        """A new bundle with `fields` replaced (planted-demo flow)."""
        return dataclasses.replace(self, **fields)
