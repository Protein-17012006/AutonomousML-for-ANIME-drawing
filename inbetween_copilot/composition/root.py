"""Production composition root.

Only this package may know all feature packages at once.  It assembles concrete
adapters and pure policies into the application-owned ``CopilotPorts`` contract.
"""
from __future__ import annotations

from inbetween_copilot.composition.correction import build_corrector
from inbetween_copilot.composition.fill import (
    build_generator,
    build_interpolator,
    build_regime_classifier,
)
from inbetween_copilot.composition.qa import build_qa_components
from inbetween_copilot.domain.character import CharacterSpec, reference_frames_for_gen
from inbetween_copilot.pipeline.ports import CopilotPorts
from inbetween_copilot.signals.motion import gap_score
from inbetween_copilot.triage.factory import make_triage_fn
from inbetween_copilot.triage.widegap import keys_from_gap


def build_real_ports(
    spec: "CharacterSpec | None",
    *,
    tau_hold: float,
    tau_snap: float,
    rife_engine,
    anisora_gen,
    breakdown_supply=None,
    vlm_fn=None,
    reason_fn=None,
    askkey_fn=None,
    use_director: bool = True,
    csq_artifact=None,
    ask_fn=None,
) -> CopilotPorts:
    """Assemble production implementations without leaking them into the pipeline."""

    qa = build_qa_components(spec, vlm_fn=vlm_fn, csq_artifact=csq_artifact)
    references = reference_frames_for_gen(spec)
    corrector = build_corrector(
        perceive_fn=qa.perceive_fn,
        rife_engine=rife_engine,
        anisora_gen=anisora_gen,
        references=references,
        reason_fn=reason_fn,
        askkey_fn=askkey_fn,
        use_director=use_director,
    )

    return CopilotPorts(
        gap_fn=gap_score,
        regime_fn=build_regime_classifier(tau_hold=tau_hold, tau_snap=tau_snap),
        interp_fn=build_interpolator(rife_engine),
        qa_fn=qa.qa_fn,
        softness_fn=qa.softness_fn,
        triage_fn=make_triage_fn(
            tau_hold=tau_hold,
            tau_snap=tau_snap,
            ask_fn=ask_fn,
        ),
        keys_needed_fn=keys_from_gap,
        gen_fn=build_generator(anisora_gen, spec),
        breakdown_supply=breakdown_supply,
        corrector=corrector,
        qa3_fn=qa.qa3_fn,
        qa_window=True,
    )
