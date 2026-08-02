"""Who the orchestrator may address. A plan step naming anything absent here is
dropped at validation, which is also the injection defence: a goal cannot reach a
target that is not already allow-listed.

Tool confirmation is READ from service.assistant.agent.TOOLS rather than copied,
so the orchestration rail and the chat rail cannot drift apart.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Optional

from service.assistant.agent import TOOLS


@dataclass(frozen=True)
class Target:
    name: str
    kind: str                       # "agent" | "tool"
    label: str
    needs_confirm: bool
    handler: Optional[Callable] = None      # agents only


# Agent descriptions are what the planner sees; keep them about WHAT the agent
# decides, not how it is implemented.
#
# (label, what the agent DECIDES, args shape, output fields a later step may read)
#
# OUTPUTS is not documentation. A step may name an earlier step's answer as
# "$<id>.<field>", and the planner can only write that if it has been told the
# field exists — the same omission that made it invent tool argument names on
# 2026-08-01. Each list below is read from the handler in
# service/orchestration/agents.py, not transcribed from a design doc: a field
# named here that the agent never returns produces a step the server rejects at
# runtime, and a field the agent returns but this text omits is one the planner
# can never learn to reference.
#
# Some agents have more than one payload SHAPE, not one shape with optional
# extras. cut_survey_agent is the sharp case: when the QA channel was down for
# the run (ctx.state["qa_degraded"]) it returns ONLY {"qa_degraded": True} —
# none of its usual accounting fields, because those verdicts would not be
# about the drawings at all. That is a different condition from "nothing was
# evaluated" (which DOES carry the full accounting payload) — see
# agents.py:290-424. Describing the accounting fields as unconditional here
# would tell the planner something untrue about a real path, not just an
# unlikely one.
_AGENT_SPECS = {
    "triage": ("Triage",
               "diagnoses why a pair was refused and how many keys to draw, and where",
               '{"index": <int, 0..n_pairs-1>}',
               "cls, confidence, evidence always; keys_suggested and brief ONLY "
               "for a gate-refused pair; out_of_population and withheld instead "
               "when the gate accepted the pair"),
    "perception": ("Perception",
                   "reports what defect the vision model saw in a pair and in which region",
                   '{"index": <int, 0..n_pairs-1>}',
                   "err_type, region, explanation; annotated_url once a marked "
                   "frame exists; box (fractional region rectangle) when one "
                   "could be located"),
    "qa_csq": ("QA/CSQ",
               "owns the calibrated pass/abstain/flag verdict for a pair",
               '{"index": <int, 0..n_pairs-1>}',
               "status, reason"),
    "cut_survey": ("Cut Survey",
                   "orders the WHOLE cut into work buckets from the calibrated "
                   "verdicts; ask it FIRST when the artist has not named a pair",
                   "{}",
                   "qa_degraded (true) ONLY when the QA channel was down for "
                   "this run — no other field is present on that path; "
                   "otherwise ALWAYS: work_order, buckets, keys_outstanding, "
                   "n_pairs, n_evaluated, not_evaluated, not_evaluated_reasons, "
                   "unreadable, withheld; plus first_index ONLY when there is "
                   "actionable work"),
}

# The planner must be told each tool's ARGUMENT SHAPE, not just its name. Without
# this it invents plausible-looking keys — live runs on 2026-08-01 produced
# remember_memory{"text":...}, remember_memory{"memory":...}, open_board{} and
# rerun_session{} — every one validated away, so the artist was told an action was
# coming that the server had already refused. Four rejected steps in twelve goals,
# all from this one omission.
_TOOL_ARGS = {
    "explain_pair":   '{"index": <int, 0..n_pairs-1>}',
    "show_annotated": '{"index": <int, 0..n_pairs-1>}',
    "open_board":     '{"index": <int, 0..n_pairs-1>}',
    "export_bundle":  '{}',
    # This lineage validates `interpolator` (PR #23's GIMM selector), NOT `engines`
    # — `_valid_rerun` here requires engines to be absent. A hint copied from the
    # research lineage would make every rerun step get rejected by the server.
    "rerun_session":  '{"cadence": 24|12|8|null, "smoothness": 1|2|null, '
                      '"interpolator": "rife"|"gimm"|null}  (at least ONE of '
                      'cadence/smoothness/interpolator must be set; never send "engines")',
    "remember_memory": '{"kind": "preference"|"show_context", "key": <an allowed key>, '
                       '"value": <short string>}',
}

_AGENT_HANDLERS: dict = {}


def register_agent(name: str, handler: Callable) -> None:
    """Bind an agent's handler. Called once by service.orchestration.agents."""
    if name not in _AGENT_SPECS:
        raise KeyError(f"unknown agent {name!r}")
    _AGENT_HANDLERS[name] = handler


def agent_names() -> tuple:
    return tuple(sorted(_AGENT_SPECS))


def tool_names() -> tuple:
    return tuple(sorted(TOOLS))


def resolve(name) -> Optional[Target]:
    if not isinstance(name, str) or not name:
        return None
    if name in _AGENT_SPECS:
        label = _AGENT_SPECS[name][0]
        return Target(name=name, kind="agent", label=label, needs_confirm=False,
                      handler=_AGENT_HANDLERS.get(name))
    spec = TOOLS.get(name)
    if spec is None:
        return None
    return Target(name=name, kind="tool", label=spec["label"],
                  needs_confirm=bool(spec["needs_confirm"]), handler=None)


def describe_for_prompt() -> str:
    lines = ['AGENTS (ask these; each may answer "no" and you must accept it):']
    for name in agent_names():
        _label, desc, args_hint, outputs = _AGENT_SPECS[name]
        lines.append(f"  {name} — {desc}; args {args_hint}")
        lines.append(f"      OUTPUTS a later step may read: {outputs}")
    lines.append("TOOLS (deterministic; NOTHING here runs until the artist accepts it):")
    for name in tool_names():
        spec = TOOLS[name]
        confirm = " [needs explicit confirmation]" if spec["needs_confirm"] else ""
        lines.append(f"  {name} — {spec['label']}{confirm}")
        lines.append(f"      args {_TOOL_ARGS.get(name, '{}')}")
    if "remember_memory" in TOOLS:
        from service.memory.models import ALLOWED_KEYS
        for kind, keys in sorted(ALLOWED_KEYS.items()):
            lines.append(f"      remember_memory {kind} keys: {', '.join(sorted(keys))}")
    lines.append("Emit args EXACTLY in these shapes. A step whose args do not match is "
                 "refused by the server and the artist is told it did not happen.")
    return "\n".join(lines)
