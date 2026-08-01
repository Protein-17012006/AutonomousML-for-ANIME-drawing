"""Assistant feature: grounded session Q&A (vault 'Web UI - Chat-First Copilot Surface' §3).

build_session_context turns retained session state into a compact fact
sheet; answer_question feeds it + the user's question to a DeepSeek ask_fn
with an answer-ONLY-from-facts contract, and degrades to a deterministic
template summary when the LLM is unconfigured/unreachable — never raises."""
from __future__ import annotations

_MAX_CTX = 6000          # hard cap: keep the prompt cheap and the box happy
_PROMPT = (
    "You are the In-Between Co-pilot's session assistant. Answer the artist's "
    "question using ONLY the session facts below. If the facts don't contain "
    "the answer, say you don't have that data. Answer in the language the "
    "question is asked in. Be concise (<=120 words).\n\nSESSION FACTS:\n{ctx}\n\n"
    "QUESTION: {q}\nANSWER:"
)


def build_session_context(state: dict) -> str:
    """Compact per-pair fact sheet from the retained session state (capped)."""
    res = state["result"]
    lines = [
        f"keys: {len(state.get('keys', []))} | pairs: {len(res.pairs)} | "
        f"auto-pass: {res.n_autopass} | corrected: {res.n_corrected} | "
        f"flagged: {len(res.flagged)} | abstained: {len(res.abstained)} | "
        f"keys requested: {res.keys_requested_total}",
    ]
    for p in res.pairs:
        qa = p.qa.status if p.qa is not None else "-"
        reason = p.qa.reason if p.qa is not None else ""
        row = f"pair {p.index}: {p.action}/{p.route or '-'} qa={qa}"
        if reason:
            row += f" ({reason})"
        corr = getattr(p, "correction", None)
        if corr is not None:
            steps = "; ".join(f"{r.action_kind} — {getattr(r, 'reason', '')}"
                              for r in corr.rounds)
            row += f" | correction[{corr.status}]: {steps}"
        # The gate's diagnosis for a refused pair — the class it recognised, the
        # measurement behind it, and the instruction it wrote for the artist. This
        # is the answer to "why was it refused" and "where do I draw", so it goes
        # in front of the agent instead of being left in the payload unread.
        triage = getattr(p, "triage", None)
        if isinstance(triage, dict) and triage:
            ev = triage.get("evidence") or {}
            facts = " ".join(f"{k}={v}" for k, v in ev.items() if v is not None)
            row += (f" | triage[{triage.get('cls', '?')}"
                    f", keys_suggested={triage.get('keys_suggested', '?')}"
                    f", confidence={triage.get('confidence', '?')}]")
            if facts:
                row += f" {facts}"
            brief = str(triage.get("brief") or "").strip()
            if brief:
                row += f" | brief: {brief}"
        # What the vision model actually saw, and where. Computed by explain_pairs
        # and stored on the session, but never shown to the agent before — so the
        # agent could offer the picture and still not say what was in it.
        exp = (state.get("explanations") or {})
        info = exp.get(p.index) or exp.get(str(p.index))
        if isinstance(info, dict) and info:
            row += (f" | vlm[{info.get('err_type', '?')}"
                    f" @ {info.get('region', '?')}]")
            note = str(info.get("explanation") or "").strip()
            if note:
                row += f" {note}"
            if info.get("annotated_url"):
                row += " | annotated image available"
        lines.append(row)
        if sum(len(ln) + 1 for ln in lines) > _MAX_CTX:
            lines.append(f"... (truncated at pair {p.index} of {len(res.pairs)})")
            break
    return "\n".join(lines)[:_MAX_CTX]


def fallback_answer(context: str) -> str:
    """Deterministic answer when the LLM is offline — mirrors decide_fixed's role."""
    head = context.splitlines()[0] if context else "no session facts"
    return ("(LLM director offline — deterministic summary) Session: " + head +
            ". Ask again once DEEPSEEK_API_KEY is configured for grounded answers.")


def answer_question(state: dict, question: str, ask_fn) -> dict:
    """Grounded answer dict {'answer', 'grounded'}; degrades, never raises."""
    ctx = build_session_context(state)
    if ask_fn is not None:
        ans = ask_fn(_PROMPT.format(ctx=ctx, q=question))
        if ans:
            return {"answer": ans, "grounded": True}
    return {"answer": fallback_answer(ctx), "grounded": False}
