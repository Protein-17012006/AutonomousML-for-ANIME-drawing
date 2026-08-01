"""The Orchestrator agent: decomposes one artist goal into a plan of steps.

It emits NO prose. The artist-facing sentence is written later by the existing
decide_agent prompt, so the rails proven under adversarial pressure are not
re-litigated by a new prompt. Never raises: an unusable reply becomes an empty
plan carrying a reason, and the caller falls through to single-turn chat.
"""
from __future__ import annotations

from service.assistant.ask import build_session_context
from service.core.json_tools import first_json_object
from service.orchestration import registry
from service.orchestration.models import MAX_PLAN_STEPS, Plan, Step

_MAX_GOAL_CHARS = 2000
_MAX_TURN_CHARS = 400
_MAX_ASK_CHARS = 300


def _prompt(ctx: str, hist: str, goal: str) -> str:
    return (
        "You are the In-Between Co-pilot's ORCHESTRATOR. Decompose the artist's "
        "goal into an ordered plan of steps. Emit NO prose and NO explanation — "
        "another agent writes the reply.\n"
        "A step addresses exactly one target below. Ask an AGENT when the artist "
        "wants a judgement or a diagnosis; call a TOOL when they want an action.\n"
        'An agent may answer "no"; plan the step anyway and let it answer.\n\n'
        + registry.describe_for_prompt() +
        "\n\nReply STRICT JSON only: "
        '{"steps": [{"target": <name>, "kind": "agent"|"tool", '
        '"ask": <short question, agents only>, "args": <object>}]}\n'
        f"At most {MAX_PLAN_STEPS} steps. Use an empty list when the goal needs no "
        "step at all (a plain question, a greeting, or anything you cannot "
        "decompose).\n\n"
        "SESSION FACTS:\n" + ctx +
        "\n\nCHAT SO FAR:\n" + (hist or "(none)") +
        "\n\nARTIST GOAL: " + goal + "\nJSON:"
    )


def _steps_from(doc: dict) -> tuple:
    raw = doc.get("steps")
    if not isinstance(raw, list):
        return ()
    steps = []
    for item in raw:
        if len(steps) >= MAX_PLAN_STEPS:
            break
        if not isinstance(item, dict):
            continue
        target = registry.resolve(item.get("target"))
        if target is None:
            continue        # unregistered target: dropped, never executed
        args = item.get("args")
        steps.append(Step(
            id=len(steps) + 1,
            target=target.name,
            # the registry decides what a target IS; the model does not get a vote
            kind=target.kind,
            ask=str(item.get("ask") or "")[:_MAX_ASK_CHARS],
            args=args if isinstance(args, dict) else {},
        ))
    return tuple(steps)


def plan_goal(state: dict, goal: str, history: list, ask_fn) -> Plan:
    """Decompose `goal` into a Plan. Never raises."""
    goal = str(goal or "")[:_MAX_GOAL_CHARS]
    if ask_fn is None:
        return Plan(goal=goal, steps=(), reason="planner unavailable (no LLM configured)")
    try:
        ctx = build_session_context(state)
        hist = "\n".join(
            f"{t.get('role', 'user')}: {t.get('text', '')[:_MAX_TURN_CHARS]}"
            for t in (history or [])[-8:])
        raw = ask_fn(_prompt(ctx, hist, goal))
    except Exception as exc:            # noqa: BLE001 — by contract this never raises
        return Plan(goal=goal, steps=(), reason=f"planner call failed: {exc}")

    try:
        doc = first_json_object(raw or "")
    except (ValueError, TypeError):
        doc = None
    if not isinstance(doc, dict):
        return Plan(goal=goal, steps=(), reason="planner reply contained no JSON object")

    steps = _steps_from(doc)
    if not steps:
        # Two very different things used to share one reason string, and the
        # difference is the whole diagnosis. An empty list is the planner USING
        # the instruction above ("a plain question, a greeting, or anything you
        # cannot decompose") - the correct answer for a goal already settled
        # earlier in the chat. A non-empty list that survives as nothing means
        # every target it named is unregistered, which is a planner/registry
        # disagreement and a defect. Reporting both as "no usable step" made the
        # second invisible behind the first.
        proposed = doc.get("steps")
        if isinstance(proposed, list) and proposed:
            return Plan(goal=goal, steps=(),
                        reason="planner named no registered target")
        return Plan(goal=goal, steps=(),
                    reason="planner judged this needs no specialist step")
    return Plan(goal=goal, steps=steps)
