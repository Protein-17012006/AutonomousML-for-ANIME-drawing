"""Application service that diagnoses a wide pair and produces a drawing brief."""
from __future__ import annotations

from dataclasses import dataclass

from inbetween_copilot.signals.motion import gap_score
from inbetween_copilot.signals.regime import classify, scene_cut
from inbetween_copilot.triage.models import TriageResult
from inbetween_copilot.triage.ports import BriefWriter
from inbetween_copilot.triage.widegap import classify_gap


@dataclass(frozen=True)
class TriagePair:
    tau_hold: float
    tau_snap: float
    brief_writer: BriefWriter

    def execute(self, a, b, pair_plan) -> TriageResult:
        has_cut = bool(scene_cut(a, b))
        regime = classify(
            [gap_score(a, b)],
            tau_hold=self.tau_hold,
            tau_snap=self.tau_snap,
            has_cut=has_cut,
        )
        diagnosis = classify_gap(
            a, b, gap=pair_plan.gap, regime=regime, has_cut=has_cut,
        )
        return TriageResult(diagnosis, self.brief_writer(diagnosis))
