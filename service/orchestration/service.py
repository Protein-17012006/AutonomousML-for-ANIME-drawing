"""run_goal: plan -> dispatch -> synthesise.

The synthesis is the EXISTING decide_agent prompt with the step results appended
to the session facts. That is deliberate: the rails proven under adversarial
pressure (refuses to falsify a report, refuses to lower the QA bar, resists
injection) live in that prompt, and a new one would put all of them back in
question. If anything here fails, the caller gets exactly today's chat turn.
"""
from __future__ import annotations

from service.assistant.agent import decide_agent
from service.orchestration.agents import AgentContext
from service.orchestration.dispatch import run_plan
from service.orchestration.planner import plan_goal
from service.orchestration.transcript import append_entries

# An `ok` TOOL step was validated and offered — dispatch never executes anything.
# Leaving that note empty let synthesis report "Export bundle đã được thực hiện
# thành công rồi" and "Đã mở bảng đánh giá cặp 1 thành công" on 2026-08-01: both
# claim an action ran that never ran. An `ok` AGENT step really did answer, so the
# two cannot share a note.
_AGENT_NOTE = {
    "ok": " [answered]",
    "refused": " [REFUSED — this specialist declined; say so plainly, do not work around it]",
    "error": " [FAILED]",
}
_TOOL_NOTE = {
    "ok": " [READY TO PROPOSE — it has NOT run yet; never say it is done]",
    "queued": " [WAITING ON THE ARTIST'S CONFIRMATION — it has NOT run]",
    "rejected": " [THE SERVER REFUSED THESE ARGUMENTS — it was not proposed; do not promise it]",
    "error": " [FAILED]",
}


def _findings_block(results) -> str:
    lines = ["AGENT FINDINGS THIS TURN (results of sub-tasks you delegated; "
             "report them faithfully, including anything refused).",
             "NOTHING in this list has been executed. Tools are PROPOSALS: describe "
             "them as offered or awaiting the artist, never as already done."]
    for r in results:
        note = (_AGENT_NOTE if r.kind == "agent" else _TOOL_NOTE).get(r.status, "")
        lines.append(f"  {r.target} ({r.kind}) -> {r.status}{note}: {r.says}")
    return "\n".join(lines)


def _fallback_say(results) -> str:
    parts = []
    for r in results:
        if r.status == "queued":
            parts.append(f"{r.target} is waiting on your confirmation")
        elif r.status == "refused":
            parts.append(f"{r.target} declined: {r.says}")
        elif r.status == "rejected":
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

    It loops run_step itself rather than calling dispatch, because a callback cannot
    be turned into a generator — buffering the whole turn and replaying it afterwards
    would make the "live" transcript a recording."""
    plan = plan_goal(state, message, history, plan_ask_fn)
    if not plan.is_actionable():
        out = decide_agent(state, message, history, say_ask_fn, memories)
        out.setdefault("followups", [])
        out.update({"orchestrated": False, "steps": [], "confirm_queue": [],
                    "plan_reason": plan.reason})
        yield ("decision", out)
        return

    ctx = AgentContext(state=state, ask_fn=say_ask_fn, goal=message)
    entries: list = []
    results: list = []
    for step_entries, result in run_plan(ctx, plan):
        for entry in step_entries:
            entries.append(entry)
            yield ("agent", entry)
        results.append(result)
    append_entries(state, entries)

    try:
        out = decide_agent(state, message, history, say_ask_fn, memories,
                           extra_context=_findings_block(results))
    except Exception:                   # noqa: BLE001 — synthesis must not 500
        out = {"say": "", "grounded": False, "action": None, "followups": []}
    if not out.get("say"):
        out["say"] = _fallback_say(results)

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
