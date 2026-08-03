"""run_goal: plan -> dispatch -> synthesise.

The synthesis is the EXISTING decide_agent prompt with the step results appended
to the session facts. That is deliberate: the rails proven under adversarial
pressure (refuses to falsify a report, refuses to lower the QA bar, resists
injection) live in that prompt, and a new one would put all of them back in
question. If anything here fails, the caller gets exactly today's chat turn.
"""
from __future__ import annotations

import time

from service.assistant.agent import decide_agent
from service.orchestration.agents import AgentContext
from service.orchestration.dispatch import run_plan
from service.orchestration.models import TranscriptEntry
from service.orchestration.planner import plan_goal
from service.orchestration.transcript import append_entries
from service.orchestration.verify import (has_hard, repair_note, summarise,
                                          violations)

VERIFIER = "verifier"

# An `ok` TOOL step was validated and offered — dispatch never executes anything.
# Leaving that note empty let synthesis report "Export bundle đã được thực hiện
# thành công rồi" and "Đã mở bảng đánh giá cặp 1 thành công" on 2026-08-01: both
# claim an action ran that never ran. An `ok` AGENT step really did answer, so the
# two cannot share a note.
_AGENT_NOTE = {
    "ok": " [answered]",
    "refused": " [REFUSED — this specialist declined; say so plainly, do not work around it]",
    "error": " [FAILED]",
    "rejected": " [NEVER REACHED THE SPECIALIST — the server could not resolve its "
               "arguments, so nothing was asked; this is neither an answer nor a "
               "refusal — do not report it as either]",
}
_TOOL_NOTE = {
    "ok": " [READY TO PROPOSE — it has NOT run yet; never say it is done]",
    "queued": " [WAITING ON THE ARTIST'S CONFIRMATION — it has NOT run]",
    "rejected": " [THE SERVER REFUSED THESE ARGUMENTS — it was not proposed; do not promise it]",
    "error": " [FAILED]",
}


# Sentences the specialist has ALREADY spoken through `says`. Repeating them as
# a "measurement" pads the context with a second copy of the same words and
# pushes the actual numbers further from the model's attention.
_PROSE_FIELDS = {"brief", "explanation", "withheld", "label", "says", "note"}
_MAX_MEASURED_FIELDS = 12
_MAX_MEASURED_CHARS = 80


def _measurements(payload: dict) -> str:
    """`key=value` for the scalar findings a specialist computed, `evidence` included.

    The payload reached the SCREEN (it rides in the transcript entry's `data`) and
    stopped there: synthesis saw `says` alone, so the model wrote about a
    measurement it had never been shown. Anything that is not a scalar — a nested
    structure, an image, a list of pairs — is deliberately left out rather than
    stringified: it would spend the context window without being readable.
    """
    if not isinstance(payload, dict):
        return ""
    flat: list[tuple[str, object]] = []
    for key, value in payload.items():
        if key in _PROSE_FIELDS:
            continue
        if key == "evidence" and isinstance(value, dict):
            flat.extend((str(k), v) for k, v in value.items()
                        if isinstance(v, (int, float, bool, str)))
        elif key == "args" and isinstance(value, dict):
            # A tool's own arguments ARE the proposal: which pair, which setting.
            flat.extend((str(k), v) for k, v in value.items()
                        if isinstance(v, (int, float, bool, str)))
        elif isinstance(value, (int, float, bool, str)):
            flat.append((key, value))
    parts = [f"{k}={str(v)[:_MAX_MEASURED_CHARS]}"
             for k, v in flat[:_MAX_MEASURED_FIELDS] if str(v) != ""]
    return ", ".join(parts)


def _findings_block(results) -> str:
    lines = ["AGENT FINDINGS THIS TURN (results of sub-tasks you delegated; "
             "report them faithfully, including anything refused).",
             "NOTHING in this list has been executed. Tools are PROPOSALS: describe "
             "them as offered or awaiting the artist, never as already done."]
    for r in results:
        note = (_AGENT_NOTE if r.kind == "agent" else _TOOL_NOTE).get(r.status, "")
        lines.append(f"  {r.target} ({r.kind}) -> {r.status}{note}: {r.says}")
        measured = _measurements(r.payload)
        if measured:
            # Named "measured" and indented under its step: these are the numbers
            # that step computed, never a second opinion about them.
            lines.append(f"      measured: {measured}")
    return "\n".join(lines)


def _fallback_say(results) -> str:
    parts = []
    for r in results:
        if r.status == "queued":
            parts.append(f"{r.target} is waiting on your confirmation")
        elif r.status == "refused":
            parts.append(f"{r.target} declined: {r.says}")
        elif r.status == "rejected":
            if r.kind == "agent":
                # Tool language ("not proposed") does not fit here: an agent is
                # never "proposed" in the first place, it is asked. This step
                # never reached the specialist at all.
                parts.append(f"{r.target} was never reached — its request "
                             "could not be resolved")
            else:
                parts.append(f"{r.target} was refused by the server and not proposed")
        elif r.status == "error":
            parts.append(f"{r.target} failed")
        elif r.says:
            parts.append(r.says)
    if not parts:
        return "(LLM director offline) Nothing to report."
    return "(LLM director offline) " + "; ".join(parts)


def _confirm_queue(results) -> list:
    return [{"tool": r.target, "args": dict(r.payload.get("args") or {}),
             "needs_confirm": True,
             "label": r.payload.get("label", r.target)}
            for r in results if r.status == "queued"]


def run_goal_stream(state: dict, message: str, history: list, *, plan_ask_fn,
                    say_ask_fn, memories=None):
    """Generator: yields ("agent", TranscriptEntry) as each utterance HAPPENS, then
    one ("decision", dict). Never raises.

    It iterates `run_plan` itself rather than calling `dispatch`, because a
    callback cannot be turned into a generator — buffering the whole turn and
    replaying it afterwards would make the "live" transcript a recording.
    `run_plan` is itself the generator that owns late binding and handoff;
    this function only drains it and re-yields its entries as they arrive."""
    plan = plan_goal(state, message, history, plan_ask_fn)
    if not plan.is_actionable():
        out = decide_agent(state, message, history, say_ask_fn, memories)
        out.setdefault("followups", [])
        out.update({"orchestrated": False, "steps": [], "confirm_queue": [],
                    "plan_reason": plan.reason})
        yield ("decision", out)
        return

    def replan(situation: str, remaining):
        """Ask the planner what should run INSTEAD of the tail. Bounded by
        dispatch: once per turn, no unplanned tool, inside the step budget."""
        queued = ", ".join(f"{s.target}({s.args})" for s in remaining) or "(none)"
        return plan_goal(state, message, history, plan_ask_fn,
                         situation=f"{situation}\nSTILL QUEUED: {queued}").steps

    ctx = AgentContext(state=state, ask_fn=say_ask_fn, goal=message)
    entries: list = []
    results: list = []
    for step_entries, result in run_plan(ctx, plan, replan=replan):
        for entry in step_entries:
            entries.append(entry)
            yield ("agent", entry)
        results.append(result)

    findings = _findings_block(results)

    def _synthesise(extra: str) -> dict:
        try:
            return decide_agent(state, message, history, say_ask_fn, memories,
                                extra_context=extra)
        except Exception:               # noqa: BLE001 — synthesis must not 500
            return {"say": "", "grounded": False, "action": None, "followups": []}

    out = _synthesise(findings)
    if not out.get("say"):
        out["say"] = _fallback_say(results)

    # The check. `_findings_block` asks the model not to overclaim; this decides
    # whether it listened, on the three things a machine can actually see.
    check = violations(out, results, state, findings)
    if check:
        note = summarise(check)
        again = _synthesise(f"{findings}\n{repair_note(check)}")
        still = violations(again, results, state, findings) if again.get("say") else check
        if again.get("say") and not has_hard(still):
            # The rewrite is clean, or its only remaining complaint is rule C —
            # which may ask for better, never demand it.
            out, text = again, f"rewritten: it {note}"
        elif has_hard(check):
            # Twice wrong about something checkable. `_fallback_say` is blunt and
            # it is true; a second wrong answer is worse than a plain one.
            out["say"] = _fallback_say(results)
            out["action"] = None
            text = f"rewritten and still wrong, so a plain summary was sent: it {note}"
        else:
            text = f"asked for a rewrite: it {note}"
        entries.append(TranscriptEntry(
            seq=max((e.seq for e in entries), default=0) + 1,
            frm=VERIFIER, to="orchestrator", kind="check", text=text,
            data={"rules": [v.rule for v in check]}, ts=time.time()))
        yield ("agent", entries[-1])

    append_entries(state, entries)

    queue = _confirm_queue(results)
    # Older clients understand one action; hand them the first thing awaiting
    # confirmation so the button still appears.
    if out.get("action") is None and queue:
        out["action"] = dict(queue[0])
    out.update({
        "orchestrated": True,
        "steps": [{"target": r.target, "kind": r.kind, "status": r.status,
                   "says": r.says, "ms": r.ms} for r in results],
        "confirm_queue": queue,
        "plan_reason": None,
    })
    out.setdefault("followups", [])
    yield ("decision", out)


def run_goal(state: dict, message: str, history: list, *, plan_ask_fn, say_ask_fn,
             memories=None, on_entry=None) -> dict:
    """Drain run_goal_stream into the plain decision dict. Never raises."""
    decision: dict = {}
    for kind, payload in run_goal_stream(state, message, history,
                                         plan_ask_fn=plan_ask_fn,
                                         say_ask_fn=say_ask_fn, memories=memories):
        if kind == "agent" and on_entry is not None:
            on_entry(payload)
        elif kind == "decision":
            decision = payload
    return decision
