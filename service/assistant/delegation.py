"""Chat-mode delegation to a specialist.

`decide_agent` is grounded Q&A plus ONE tool proposal per turn — there is no
tool-result loop to hang a data fetch on. Asking a specialist is not a tool: a
tool is an artist-facing proposal that runs on confirmation, while a specialist's
answer is data the director then reports. So the route runs the ask and re-enters
the SAME prompt with the answer in `extra_context` — the seam orchestration
already uses at service/orchestration/service.py:111-112. Both modes therefore
reach one handler and cannot give two answers about one pair, which is the defect
class already fixed once at e0ab729d.

WHY THE RUNNER IS INJECTED: `service/assistant/**` may not import
`service.orchestration` — the edge is one-way and a back-import makes the graph
cyclic (test_architecture.test_assistant_never_imports_orchestration). The
handler is therefore supplied at composition time by service/app.py, which is
allowed to see both. With nothing registered, `resolve_specialist` returns the
turn untouched: the director answers from the facts alone, which is exactly the
degradation an unreachable specialist would produce.

NOT wired into POST /session/{sid}/agent/stream. That route streams `say`
token-by-token, so a re-entry would emit one answer on screen and then supersede
it. The canonical SPA calls the blocking route
(frontend/src/components/copilot/api.ts:390); the stream route keeps the old
behaviour and answers a refusal question from the pointer alone until converted.
"""
from __future__ import annotations

# name -> (state, index, message, ask_fn) -> str
_RUNNERS: dict = {}


def set_specialist_runner(name: str, runner) -> None:
    """Bind a specialist's handler. Called once, at composition time."""
    _RUNNERS[name] = runner


def resolve_specialist(state: dict, message: str, output: dict, ask_fn,
                       memories=None, history=None) -> dict:
    """Run the specialist the director asked for and answer again with its words.

    Returns `output` unchanged when nothing was asked or nothing is registered."""
    asked = output.get("specialist")
    if not isinstance(asked, dict):
        return output
    runner = _RUNNERS.get(asked.get("name"))
    if runner is None:
        return output

    from service.assistant.agent import decide_agent

    said = runner(state, asked["index"], message, ask_fn)
    if not said:
        return output

    second = decide_agent(
        state, message, history or [], ask_fn, memories,
        extra_context=(f"{asked['name'].upper()} SPECIALIST — you asked it, "
                       "report it faithfully and add nothing it did not say:\n"
                       f"  {said}"))
    # One hop per turn: a second ask would loop, and the answer is already in
    # front of the director.
    second["specialist"] = None
    return second
