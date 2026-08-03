"""What the triage specialist SAYS when the artist asks about a refused pair.

Until 2026-08-03 `triage_agent` replayed the stored `brief` verbatim. The brief
is written once, during the pipeline, by a prompt that knew no question — so two
different questions about one pair returned byte-identical text, and the answer
could never be about what was asked.

The MEASUREMENTS stay frozen: regenerating a diagnosis can contradict what is on
screen, the failure Spec 4 closed. Only the ANSWER is written fresh.

The two rules below exist because of one live answer. Asked why a pair was
refused, the director wrote *"the gate didn't stop just because of gap size — it
saw a pose snap … the character crosses the frame with a shift"*. Both halves are
wrong: the gate compares gap to tau and nothing else, and `pose_snap` REQUIRES
shift_frac < 0.20, which is precisely "not explained by the character shifting".
"""
from __future__ import annotations

# Ordered so the reason comes before the description.
_EVIDENCE_KEYS = (
    "gap", "tau_gate", "shift_frac", "regime",
    "hot_cell", "hot_cell_ratio",
    "reading_what_moved", "reading_abrupt", "reading_difficulty",
    "reading_region", "reading_note", "reading_confirmed",
    "keys_from_signal", "keys_adjusted_why", "keys_unadjusted_why",
)

_GATE_RULES = (
    "HOW THE GATE ACTUALLY DECIDED\n"
    "  The gate compares gap against tau_gate and NOTHING ELSE. gap >= tau_gate "
    "means refuse. `cls` was written AFTER the refusal to describe the pair; it "
    "is NEVER the reason, and you must never write that the gate saw, detected, "
    "recognised or noticed it.\n"
    "  `pose_snap` in particular is the RESIDUAL bucket: not a scene cut, not a "
    "global translation (shift_frac < 0.20), and gap < 0.090 — meaning the gap "
    "is on the SMALL side of the refused range. Never describe it as the "
    "character shifting or crossing the frame: shift_frac < 0.20 rules that out.\n"
)

_COMPARISON_RULE = (
    "IF THE ARTIST COMPARES PAIRS OR DISPUTES THE DECISION\n"
    "  Add ONE sentence: gap is a whole-frame pixel difference that saturates on "
    "line art once the lines stop overlapping, so it must not be read as how far "
    "something moved, and two pairs can be ordered the wrong way round.\n"
)


_OVERLAY_RULE = (
    "WHERE TO POINT WHEN ASKED\n"
    "  A key-travel overlay for this pair ALREADY EXISTS and is on the artist's "
    "review board: the held line in grey, where the drawing IS in red, where it "
    "MOVES TO in blue. If they ask where the change is, point them at it — and "
    "NEVER say there is nothing to show them. Saying no cell stood out is "
    "correct; saying there is nothing to look at is not.\n"
)


def _facts(payload: dict) -> str:
    ev = dict(payload.get("evidence") or {})
    lines = [
        f"  cls = {payload.get('cls', '?')}"
        "   <- a description written AFTER the refusal, never the reason",
        f"  keys_suggested = {payload.get('keys_suggested', '?')}",
    ]
    lines += [f"  {k} = {ev[k]}" for k in _EVIDENCE_KEYS if ev.get(k) is not None]
    # State the negative result rather than leaving the key out. Absence read as
    # "not localized" is an inference; this is the measurement.
    if ev.get("hot_cell_searched") and ev.get("hot_cell") is None:
        lines.append(
            "  hot_cell = NONE — the localizer ran and no single cell stood out "
            "(none beat the runner-up by 1.4x), so the change is spread across "
            "the drawing rather than sitting in one place")
    brief = str(payload.get("brief") or "").strip()
    if brief:
        lines.append(f"  drawing brief already written for this pair: {brief}")
    return "\n".join(lines)


def prompt_for(question: str, payload: dict, index=None, overlay: bool = False) -> str:
    where = f"pair {index}" if index is not None else "this pair"
    return (
        "You are the In-Between Co-pilot's gap-triage specialist. An artist is "
        f"asking about {where} — ONE key pair the interpolable gate refused, so "
        "no in-between frame was ever generated for it.\n\n"
        "WHAT YOU MEASURED (your only facts — never invent another):\n"
        + _facts(payload) + "\n\n"
        + _GATE_RULES + "\n" + _COMPARISON_RULE
        + ("\n" + _OVERLAY_RULE if overlay else "") + "\n"
        "Answer the question that was asked, in the artist's own language, in at "
        "most 90 words. Whenever you give the reason, state gap and tau_gate as "
        "numbers. Never claim to have seen more than the two key drawings.\n\n"
        f"QUESTION: {question}\nANSWER:"
    )


def deterministic_answer(payload: dict, index=None) -> str:
    """The answer when the LLM is unreachable. States the real reason, and never
    presents `cls` as it."""
    ev = dict(payload.get("evidence") or {})
    gap, tau = ev.get("gap"), ev.get("tau_gate")
    where = f"Pair {index}" if index is not None else "This pair"
    if gap is not None and tau is not None:
        head = (f"{where} was refused because its gap {gap} reached this "
                f"session's threshold {tau}; that comparison is the whole "
                "decision.")
    else:
        head = f"{where} was refused by the interpolable gate."
    cls = payload.get("cls")
    tail = f" Described afterwards as {cls}." if cls else ""
    brief = str(payload.get("brief") or "").strip()
    return head + tail + (f" {brief}" if brief else "")


def answer_refusal(question: str, payload: dict, ask_fn, index=None,
                   overlay: bool = False) -> str:
    """The specialist's answer to THIS question, grounded in the STORED payload."""
    if ask_fn is not None:
        try:
            said = (ask_fn(prompt_for(question, payload, index, overlay)) or "").strip()
        except Exception:      # noqa: BLE001 — a dead LLM costs the wording, not the answer
            said = ""
        if said:
            return said
    return deterministic_answer(payload, index)
