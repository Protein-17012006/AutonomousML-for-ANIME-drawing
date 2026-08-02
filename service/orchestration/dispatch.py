"""Runs a Plan step by step and records the conversation.

Confirmation authority is READ from the assistant's TOOLS table, never copied:
a confirm-gated tool is QUEUED here and executed only after the artist accepts,
exactly as in single-turn chat. Nothing in this module runs a tool's effect.
"""
from __future__ import annotations

import time
from dataclasses import replace

from service.assistant.agent import TOOLS
from service.orchestration import agents as _agents      # noqa: F401 — binds handlers
from service.orchestration import registry
from service.orchestration.binding import is_reference, resolve_args
from service.orchestration.models import (MAX_PLAN_STEPS, Step, StepResult,
                                          TranscriptEntry)

ORCHESTRATOR = "orchestrator"

_ENTRY_KIND_FOR = {"ok": "reply", "refused": "refuse", "queued": "queue",
                   "rejected": "error", "error": "error"}


class Seq:
    """Monotonic transcript sequence, owned by one turn."""

    def __init__(self):
        self.n = 0

    def next(self) -> int:
        value = self.n
        self.n += 1
        return value


def _entry(seq, frm, to, kind, text, data=None, ms=0) -> TranscriptEntry:
    return TranscriptEntry(seq=seq.next(), frm=frm, to=to, kind=kind,
                           text=text, data=data or {}, ms=ms, ts=time.time())


def _run_tool(step, n_pairs: int, state=None) -> StepResult:
    spec = TOOLS.get(step.target)
    if spec is None:                    # unreachable via the planner; defensive
        return StepResult(step.id, step.target, "tool", "rejected",
                          says=f"{step.target} is not a tool I can call.")
    try:
        valid = bool(spec["validate"](step.args, n_pairs, state))
    except Exception:                   # noqa: BLE001 — a validator must not escape
        valid = False
    if not valid:
        return StepResult(
            step.id, step.target, "tool", "rejected",
            says=(f"The server refused {spec['label']} with those arguments, so "
                  "it was not proposed."),
            payload={"args": dict(step.args)})
    if spec["needs_confirm"]:
        return StepResult(
            step.id, step.target, "tool", "queued",
            says=f"{spec['label']} is ready and waiting on your confirmation.",
            payload={"args": dict(step.args), "needs_confirm": True,
                     "label": spec["label"]})
    # Validated and offered — NOT executed. Dispatch runs no tool effect at all, so
    # the transcript must not read like a completed action.
    return StepResult(
        step.id, step.target, "tool", "ok",
        says=f"{spec['label']} is ready to propose (not run yet).",
        payload={"args": dict(step.args), "needs_confirm": False,
                 "label": spec["label"]})


def run_step(ctx, step, seq, sources=None, asker=ORCHESTRATOR):
    """Run ONE step. Returns (entries, result) — the caller decides what to do with
    the entries, which is what lets the SSE route stream them as they happen.

    `sources` holds the payloads of steps that have already run, so this step's
    args may name one. `asker` is who addressed this step: the orchestrator, or
    the AGENT that handed the work over."""
    target = registry.resolve(step.target)
    if target is None:                  # unreachable via the planner; defensive
        return [], None

    resolved, bound, error = resolve_args(step.args, sources)
    ask_data = dict(step.args) if resolved is None else dict(resolved)
    if bound:
        # Both ends, or the mechanism is invisible.
        ask_data["_bound"] = dict(bound)
    entries = [_entry(seq, asker, step.target, "ask",
                      step.ask or f"{step.target} {ask_data}", data=ask_data)]
    started = time.monotonic()

    if error:
        # The server refused these arguments before anyone was asked. Same status
        # a tool gets for a failed validation, and it reaches synthesis the same way.
        result = StepResult(step.id, step.target, target.kind, "rejected", says=error)
        entries.append(_entry(seq, step.target, asker, "error", error,
                              data={"status": "rejected"}))
        return entries, result

    step = replace(step, args=resolved)

    if target.kind == "agent":
        handler = target.handler
        if handler is None:
            result = StepResult(step.id, step.target, "agent", "error",
                                says=f"{step.target} has no handler bound.")
        else:
            try:
                result = handler(ctx, step)
            except Exception as exc:    # noqa: BLE001 — contained by contract
                result = StepResult(step.id, step.target, "agent", "error",
                                    says=f"{step.target} failed: {exc}")
    else:
        result = _run_tool(step, len(ctx.state["result"].pairs), ctx.state)

    if not result.ms:
        result = replace(result, ms=int((time.monotonic() - started) * 1000))

    entries.append(_entry(seq, step.target, asker,
                          _ENTRY_KIND_FOR.get(result.status, "reply"), result.says,
                          data={"status": result.status, **result.payload},
                          ms=result.ms))
    return entries, result


def _handoff_refusal(result, is_born: bool, handed_to: set, planned: int) -> str:
    """Why this handoff must NOT run — "" means run it. Never raises.

    A handoff is an agent choosing the next specialist. It is honoured only from a
    refusal ("I cannot help, but X can"), never toward a tool (that would queue an
    action the planner never proposed and the artist never saw in the plan), and
    never past the caps that keep one turn finite."""
    handoff = getattr(result, "handoff", None)
    if not isinstance(handoff, dict) or not handoff:
        return ""                       # nothing offered; nothing to report
    if result.status != "refused":
        return "a handoff is only honoured from a refusal"
    if is_born:
        return "handoff depth is 1: a handoff-born step may not hand off again"
    to = handoff.get("to")
    target = registry.resolve(to) if isinstance(to, str) else None
    if target is None:
        return f"handoff to unknown target {to!r}"
    if target.kind != "agent":
        return (f"handoff to '{to}' refused: it is a tool, and an agent may not "
                "queue an action the planner never proposed")
    if to in handed_to:
        return f"{to} already received a handoff this turn"
    if planned >= MAX_PLAN_STEPS:
        return f"the {MAX_PLAN_STEPS}-step budget for this turn is spent"
    args = handoff.get("args")
    if not isinstance(args, dict) or any(is_reference(v) for v in args.values()):
        return "handoff args must be plain values"
    return ""


def run_plan(ctx, plan):
    """Generator: yields (entries, result) for each step actually run, in order.

    Owns the work queue, late binding and handoff. A handoff-born step spends the
    SAME budget as a planned one — there is no separate allowance — and it is
    addressed by the agent that authored it, not by the orchestrator. Never raises."""
    if not plan.is_actionable():
        return
    seq = Seq()
    queue = [(step, ORCHESTRATOR, False) for step in plan.steps]
    sources: dict = {}
    handed_to: set = set()
    ran = 0
    next_id = max((step.id for step in plan.steps), default=0)

    while queue and ran < MAX_PLAN_STEPS:
        step, asker, is_born = queue.pop(0)
        entries, result = run_step(ctx, step, seq, sources, asker)
        if result is None:
            continue
        ran += 1
        sources[step.id] = {"kind": result.kind, "payload": dict(result.payload)}

        refusal = _handoff_refusal(result, is_born, handed_to, ran + len(queue))
        handoff = getattr(result, "handoff", None)
        if isinstance(handoff, dict) and handoff:
            if refusal:
                # Dropped, never swallowed: a mechanism nobody can see is a
                # mechanism nobody can trust.
                entries.append(_entry(seq, step.target, ORCHESTRATOR, "error",
                                      f"handoff to {handoff.get('to')!r} not run: "
                                      f"{refusal}",
                                      data={"status": "handoff_dropped"}))
            else:
                next_id += 1
                handed_to.add(handoff["to"])
                queue.append((Step(next_id, handoff["to"], "agent",
                                   ask=str(handoff.get("why") or "")[:300],
                                   args=dict(handoff.get("args") or {})),
                              step.target, True))

        if ran >= MAX_PLAN_STEPS and queue:
            # The cap just closed the loop with work still queued (planned steps
            # beyond MAX_PLAN_STEPS, or a handoff accepted too late to run). The
            # old `for step in plan.steps` loop ran every step; this cap silently
            # drops the rest unless it says so here — the same silent-drop this
            # task went to trouble to avoid for handoffs.
            entries.append(_entry(seq, ORCHESTRATOR, ORCHESTRATOR, "error",
                                  f"{len(queue)} step(s) not run: the "
                                  f"{MAX_PLAN_STEPS}-step budget for this turn "
                                  "is spent",
                                  data={"status": "plan_truncated",
                                       "not_run": len(queue)}))
        yield entries, result


def dispatch(ctx, plan, on_entry=None) -> list:
    """Execute `plan` against `ctx`. Returns one StepResult per step, in order.
    Never raises: a handler that explodes becomes an `error` and the plan carries on."""
    results: list = []
    for entries, result in run_plan(ctx, plan):
        if on_entry is not None:
            for entry in entries:
                on_entry(entry)
        results.append(result)
    return results
