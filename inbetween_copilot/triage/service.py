"""Application service that diagnoses a wide pair and produces a drawing brief."""
from __future__ import annotations

from dataclasses import dataclass, replace

from inbetween_copilot.signals.motion import gap_score
from inbetween_copilot.signals.regime import classify, scene_cut
from inbetween_copilot.triage.models import TriageResult
from inbetween_copilot.triage.ports import BriefWriter
from inbetween_copilot.triage.reading import (
    adjust_keys,
    agrees_with_measurement,
    hot_cell,
    read_keys,
)
from inbetween_copilot.triage.widegap import classify_gap


@dataclass(frozen=True)
class TriagePair:
    tau_hold: float
    tau_snap: float
    brief_writer: BriefWriter
    # Reads the two key drawings. None keeps the old scalar-only diagnosis, so
    # the stub engines and any deployment without a VLM behave exactly as before.
    key_vlm_fn: object = None

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
        diagnosis = self._with_drawing_evidence(a, b, diagnosis)
        return TriageResult(diagnosis, self.brief_writer(diagnosis))

    def _with_drawing_evidence(self, a, b, diagnosis):
        """Add what the DRAWINGS show, and let it move the key budget.

        A scene cut is exempt: there is nothing to in-between across it, so its
        key count is 0 by definition and no reading may raise it.

        Every number stays auditable. `keys_from_signal` keeps what the
        calibrated buckets said, and `keys_adjusted_why` names the reason, so a
        budget the vision model moved can never be mistaken for one the signals
        produced.
        """
        evidence = dict(diagnosis.evidence or {})
        located = hot_cell(a, b)
        if located is not None:
            cell, score, ratio = located
            evidence["hot_cell"] = cell
            evidence["hot_cell_score"] = score
            evidence["hot_cell_ratio"] = None if ratio == float("inf") else ratio
        if str(diagnosis.cls) == "scene_cut":
            return replace(diagnosis, evidence=evidence)

        reading = read_keys(a, b, self.key_vlm_fn, located=located)
        if not reading.available:
            return replace(diagnosis, evidence=evidence)
        evidence["reading_what_moved"] = reading.what_moved
        evidence["reading_abrupt"] = reading.appears_abruptly
        evidence["reading_difficulty"] = reading.difficulty
        # Always recorded, not only on disagreement: an agreement nobody can see
        # is an agreement nobody can check, and this number is the only thing
        # standing between a coarse model and a calibrated prescription.
        evidence["reading_region"] = reading.region or "unstated"
        if reading.note:
            evidence["reading_note"] = reading.note

        # The description is kept either way — it is still the only thing that
        # names the subject. But it may only move the CALIBRATED key budget when
        # it is demonstrably about the part that actually changed. Observed on a
        # real pair: the measurement said `bc` (a hand entering) while the model
        # described the head and shoulders, and on that reading the budget went
        # DOWN. A prescription is not the place to trust an unconfirmed subject.
        agrees = agrees_with_measurement(reading, located)
        if agrees is False:
            evidence["reading_confirmed"] = False
            evidence["reading_region"] = reading.region
            evidence["keys_unadjusted_why"] = (
                f"the vision model described the {reading.region} while the "
                f"measured change is in the {located[0]}; the budget stays as "
                "the calibrated signals set it")
            return replace(diagnosis, evidence=evidence)
        if agrees is True:
            evidence["reading_confirmed"] = True

        keys, why = adjust_keys(diagnosis.keys_suggested, reading)
        if why:
            evidence["keys_from_signal"] = diagnosis.keys_suggested
            evidence["keys_adjusted_why"] = why
        return replace(diagnosis, keys_suggested=keys, evidence=evidence)
