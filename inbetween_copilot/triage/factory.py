"""Factory for the real (signals-based class + DeepSeek brief) triage_fn.

Lives in inbetween_copilot/ (not service/) so both service.infrastructure.engines.box_engines
(Task 8) and inbetween_copilot.pipeline.wiring.build_real_callables (Task 10)
can wire the same triage_fn without an upward import from pipeline/ into
service/. service.infrastructure.engines re-exports make_triage_fn at module level so
`from service.infrastructure.engines import make_triage_fn` keeps working for callers/tests
that expect it there.

All imports below are kept INSIDE make_triage_fn (lazy) so this module itself
stays cheap to import from anywhere -- mirrors the _stub_triage_fn pattern in
service/engines.py.
"""
from __future__ import annotations


def make_triage_fn(*, tau_hold: float, tau_snap: float, ask_fn=None):
    """Real triage: signals-based class + DeepSeek brief (template on any failure).
    ask_fn = director_llm.make_ask_fn() product, or None -> template-only."""
    import dataclasses

    from inbetween_copilot.signals.motion import gap_score
    from inbetween_copilot.signals.regime import classify, scene_cut
    from inbetween_copilot.triage.brief import brief_prompt, template_brief
    from inbetween_copilot.triage.widegap import classify_gap

    def triage_fn(a, b, pp):
        has_cut = bool(scene_cut(a, b))
        regime = classify([gap_score(a, b)], tau_hold=tau_hold,
                          tau_snap=tau_snap, has_cut=has_cut)
        t = classify_gap(a, b, gap=pp.gap, regime=regime, has_cut=has_cut)
        brief = ""
        if ask_fn is not None:
            brief = (ask_fn(brief_prompt(t)) or "").strip()
        return {**dataclasses.asdict(t), "brief": brief or template_brief(t)}

    return triage_fn
