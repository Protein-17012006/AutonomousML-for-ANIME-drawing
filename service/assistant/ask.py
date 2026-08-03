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
    # The session's OWN configuration. Without it the agent cannot tell a real
    # change from a no-op — on 2026-08-01 it proposed rerun_session{smoothness: 2}
    # against a session already running at smoothness 2, offering a no-op as an
    # improvement — and /ask could not answer "what cadence am I running?" at all.
    cfg = state.get("cfg")
    if cfg is not None:
        lines.append(
            f"settings: cadence={getattr(cfg, 'cadence_fps', '?')}fps "
            f"smoothness=x{getattr(cfg, 'smoothness', '?')} "
            f"interpolator={getattr(cfg, 'interpolator', '?')} "
            f"tau_gate={getattr(cfg, 'tau_gate', '?')} "
            "(a pair is refused when its gap reaches tau_gate — that comparison "
            "is the entire gate decision; the pair's class is a description "
            "written afterwards, never the reason)")
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
        # The MEASUREMENT the gate compared, for EVERY pair. Without it the
        # artist cannot compare two pairs at all — which is the question that
        # started this: "pair 5's gap looks bigger and it was not refused".
        # Type-checked, not just None-checked: this fact sheet is built on every
        # chat turn, and an unguarded format on a pair carrying anything other
        # than a number raises straight through the whole turn.
        gap = getattr(p, "gap", None)
        if isinstance(gap, (int, float)) and not isinstance(gap, bool):
            row += f" gap={gap:.5f}"
        # The DIAGNOSIS is held by the triage specialist and deliberately NOT
        # copied here. This row used to carry cls, the whole evidence dict and
        # the brief, and that had two costs: the director never had to ask anyone
        # (audit 2026-08-02 — routed 13/14, cooperated 0/14, because a literal was
        # already in front of it), and the frozen brief was the string replayed
        # verbatim to every question about the pair.
        if isinstance(getattr(p, "triage", None), dict) and p.triage:
            row += " | gate diagnosis held by triage — propose the triage tool to get it"
        # A refused pair has no generated frame and no annotated image, but it
        # DOES have this: the two keys drawn over each other. Announced because
        # "where is the change?" was answered "there is nothing to point at"
        # while the file already existed.
        overlays = state.get("pair_keys") or {}
        if overlays.get(p.index) or overlays.get(str(p.index)):
            row += (" | key-travel overlay available (held line grey, where the "
                    "drawing is red, where it moves to blue)")
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
