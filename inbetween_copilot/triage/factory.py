"""Factory for the real (signals-based class + DeepSeek brief) triage_fn.

Lives in inbetween_copilot/ (not service/) so both service.infrastructure.engines.box_engines
    (Task 8) and inbetween_copilot.composition.build_real_ports (Task 10)
can wire the same triage_fn without an upward import from pipeline/ into
service/. service.infrastructure.engines re-exports make_triage_fn at module level so
`from service.infrastructure.engines import make_triage_fn` keeps working for callers/tests
that expect it there.

All imports below are kept INSIDE make_triage_fn (lazy) so this module itself
stays cheap to import from anywhere -- mirrors the _stub_triage_fn pattern in
service/engines.py.
"""
from __future__ import annotations


def make_triage_fn(*, tau_hold: float, tau_snap: float, ask_fn=None,
                   key_vlm_fn=None):
    """Real triage: signals-based class + DeepSeek brief (template on any failure).

    ask_fn = director_llm.make_ask_fn() product, or None -> template-only.
    key_vlm_fn = a (prompt, frames) -> dict caller that reads the two KEY
    drawings; None keeps the scalar-only diagnosis this had before, which is
    what the stub engines and any VLM-less deployment get.
    """
    from inbetween_copilot.triage.brief import LLMBriefWriter, TemplateBriefWriter
    from inbetween_copilot.triage.service import TriagePair

    writer = LLMBriefWriter(ask_fn) if ask_fn is not None else TemplateBriefWriter()
    service = TriagePair(tau_hold=tau_hold, tau_snap=tau_snap, brief_writer=writer,
                         key_vlm_fn=key_vlm_fn)

    def triage_fn(a, b, pp):
        return service.execute(a, b, pp).to_payload()

    return triage_fn
