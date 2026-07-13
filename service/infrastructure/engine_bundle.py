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

from inbetween_copilot.pipeline.ports import CopilotPorts

# The fields run_copilot() accepts as kwargs — everything else is service-only.
_SERVICE_ONLY = ("rife_engine", "vlm_struct_fn", "csq_calibrator", "vlm_status")


@dataclasses.dataclass
class EngineBundle(CopilotPorts):
    """Service runtime bundle extending the core-owned co-pilot port contract."""

    # --- service-only (never reach run_copilot) ---
    rife_engine: "object | None" = None      # raw [a, mid, b] (demo + smoothness x4)
    vlm_struct_fn: "object | None" = None    # explainability layer
    csq_calibrator: "dict | None" = None       # UI trust dial (box only)
    vlm_status: dict = dataclasses.field(default_factory=dict)  # degraded-QA flag

    @classmethod
    def from_ports(cls, ports: CopilotPorts, **service_fields) -> "EngineBundle":
        return cls(**ports.as_kwargs(), **service_fields)

    def copilot_kwargs(self) -> dict:
        """Exactly the kwargs run_copilot accepts (was: dict-filter against a
        magic string set in service/runner.py)."""
        return self.as_kwargs()
