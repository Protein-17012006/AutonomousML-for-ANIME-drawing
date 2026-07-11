"""User-Interaction Agent (UIA, agent #3).
decide_agent() extends ask.py's grounded-Q&A with ONE optional tool
proposal per turn. Degrades cleanly when LLM is unavailable — never raises.
"""
from __future__ import annotations
import json
from service.ask import build_session_context, fallback_answer

_ALLOWED_CADENCE = {24, 12, 8}
_ALLOWED_SMOOTHNESS = {1, 2}   # x4 descoped 2026-07-06
_ALLOWED_ENGINES = {"box", "stub"}

def _valid_index(args: dict, n_pairs: int) -> bool:
    return isinstance(args.get("index"), int) and 0 <= args["index"] < n_pairs

def _valid_rerun(args: dict, n_pairs: int) -> bool:
    ok = (
        (args.get("cadence") in _ALLOWED_CADENCE or args.get("cadence") is None)
        and (args.get("smoothness") in _ALLOWED_SMOOTHNESS or args.get("smoothness") is None)
        and (args.get("engines") in _ALLOWED_ENGINES or args.get("engines") is None)
    )
    changed = any(args.get(k) is not None for k in ("cadence", "smoothness", "engines"))
    return ok and changed

TOOLS = {
    "explain_pair":  {"needs_confirm": False, "validate": _valid_index,  "label": "Explain pair"},
    "open_board":    {"needs_confirm": False, "validate": _valid_index,  "label": "Open review board"},
    "export_bundle": {"needs_confirm": False, "validate": lambda a, n: a in ({}, None), "label": "Export bundle"},
    "rerun_session": {"needs_confirm": True,  "validate": _valid_rerun,  "label": "Re-run session"},
}

def _prompt(ctx: str, hist: str, q: str) -> str:
    return (
        "You are the In-Between Co-pilot's session agent. Using ONLY the session "
        "facts below, reply to the artist AND optionally propose ONE tool call.\n"
        "Tools (use null when no tool fits):\n"
        '  explain_pair  args {"index": int}\n'
        '  open_board    args {"index": int}\n'
        '  export_bundle args {}\n'
        '  rerun_session args {"cadence": 24|12|8|null, "smoothness": 1|2|null, "engines": "box"|"stub"|null}\n'
        'Reply STRICT JSON only: {"say": "<=100 words", "tool": <name or null>, "args": <object or null>}\n\n'
        "SESSION FACTS:\n" + ctx + "\n\nCHAT SO FAR:\n" + (hist or "(none)") +
        "\n\nUSER: " + q + "\nJSON:"
    )

def decide_agent(state: dict, message: str, history: list[dict], ask_fn) -> dict:
    """Returns {say, grounded, action}. Never raises."""
    ctx = build_session_context(state)
    hist = "\n".join(f"{t.get('role','user')}: {t.get('text','')}" for t in history[-8:])

    if ask_fn is None:
        return {"say": fallback_answer(ctx), "grounded": False, "action": None}

    raw = ask_fn(_prompt(ctx, hist, message))
    if not raw:
        return {"say": fallback_answer(ctx), "grounded": False, "action": None}

    try:
        doc = json.loads(raw[raw.index("{"):raw.rindex("}") + 1])
        say  = str(doc.get("say") or "").strip()
        tool = doc.get("tool")
        args = doc.get("args") or {}
    except (ValueError, TypeError):
        return {"say": raw.strip()[:800], "grounded": True, "action": None}

    spec = TOOLS.get(tool)
    n_pairs = len(state["result"].pairs)
    if spec is None or not spec["validate"](args, n_pairs):
        return {"say": say or fallback_answer(ctx), "grounded": True, "action": None}

    return {
        "say": say or spec["label"],
        "grounded": True,
        "action": {
            "tool": tool,
            "args": args,
            "needs_confirm": spec["needs_confirm"],
            "label": spec["label"],
        },
    }