"""Application service facade for running the co-pilot workflow."""
from __future__ import annotations

from dataclasses import dataclass

from inbetween_copilot.pipeline.copilot import run_copilot
from inbetween_copilot.pipeline.models import CopilotCfg, CopilotResult
from inbetween_copilot.pipeline.ports import CopilotPorts


@dataclass(frozen=True)
class RunCopilot:
    ports: CopilotPorts

    def execute(self, keys, *, cfg: CopilotCfg | None = None,
                on_pair=None) -> CopilotResult:
        return run_copilot(
            keys,
            cfg=cfg or CopilotCfg(),
            on_pair=on_pair,
            **self.ports.as_kwargs(),
        )
