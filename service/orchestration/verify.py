"""Check the synthesised reply against what the agents actually did.

`_findings_block` enforces its invariants by ASKING the model not to lie
("it has NOT run yet; never say it is done"). Every one of those strings was
added after a live incident, which is the tell: a prompt instruction is not an
invariant, and the next incident writes the next string.

WHAT THIS CANNOT DO, stated plainly because overclaiming it would be the same
failure the product exists to prevent: it cannot detect a completion claim
written in free prose. The agent replies in the artist's language, so
"đã được thực hiện thành công rồi" offers nothing to match on, in any tokenizer.
The prompt notes remain the layer above this one.

WHAT IT DOES is set a floor a machine can hold:

  B (hard) a filename in the reply must be one this session has, or one the
           model was shown.
  C (soft) a DECIMAL measurement must be traceable to what the model was shown.

Hard violations may end in a downgrade to the plain summary. Rule C may not:
synthesis legitimately derives figures, so a false alarm must never be able to
throw away a good answer — it buys one rewrite and nothing more.

THERE IS NO RULE A, and the reason is worth keeping. It was specified as "an
action the server refused this turn must not be offered anyway" and written
first; its test then refused to go red. `decide_agent` already validates every
proposal and returns `action: None` with `rejected_tool` set when the server
will not run it (service/assistant/agent.py:339-347), so the only turn where
such a rule could fire is one where the model re-proposes the SAME tool with
DIFFERENT, valid arguments — which is legitimate. A rule that can fire only on
a false positive is worse than no rule, so it was dropped rather than kept for
the look of the thing. See test_orchestration_verify.py.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

HARD = "hard"
SOFT = "soft"

# Produced by every run under the session directory, so they are always legitimate
# to name even when no step mentioned them.
_CANONICAL_ARTEFACTS = {
    "montage.png", "report.md", "report.json", "reconstructed.mp4",
    "compare.mp4", "bundle.zip", "workspace.v1.json",
}

_FILE_RE = re.compile(r"[\w./\\-]*\w\.(?:png|jpe?g|gif|webp|mp4|mov|md|json|zip|csv)\b",
                      re.IGNORECASE)
# A decimal, with an optional percent sign. Bare integers are deliberately NOT
# matched — see the module docstring.
_DECIMAL_RE = re.compile(r"\d+[.,]\d+\s*%?|\d+\s*%")
_NUMBER_RE = re.compile(r"\d+(?:[.,]\d+)?")


@dataclass(frozen=True)
class Violation:
    rule: str
    severity: str
    message: str


def _facts(state: dict) -> str:
    """The same session facts the model was given. Never raises: a verifier that
    can break the turn it is checking is worse than the defect it looks for."""
    try:
        from service.assistant.ask import build_session_context
        return build_session_context(state) or ""
    except Exception:                   # noqa: BLE001 — by contract
        return ""


def _known_files(state: dict, shown: str) -> set[str]:
    known = set(_CANONICAL_ARTEFACTS)
    for key in ("pair_mids", "pair_keys", "key_urls"):
        for value in (state.get(key) or {}).values():
            if isinstance(value, str):
                known.add(value)
                known.add(value.rsplit("/", 1)[-1])
    for info in (state.get("explanations") or {}).values():
        url = info.get("annotated_url") if isinstance(info, dict) else None
        if isinstance(url, str):
            known.add(url)
            known.add(url.rsplit("/", 1)[-1])
    # Anything already in front of the model is quotation, not invention.
    for match in _FILE_RE.finditer(shown):
        known.add(match.group(0))
        known.add(match.group(0).rsplit("/", 1)[-1])
    return known


def _numbers(text: str) -> set[str]:
    return {m.group(0).replace(",", ".") for m in _NUMBER_RE.finditer(text)}


def _traceable(token: str, context: set[str]) -> bool:
    """Is this decimal explainable by something the model was shown?

    Three ways, in order of how often they occur in a real answer: it was quoted
    verbatim; it was ROUNDED (0.0503 -> 0.05, so the written form prefixes a
    known one); or it was written as a PERCENTAGE of one (0.05 -> 5%).
    """
    percent = token.endswith("%")
    raw = token.rstrip("%").strip().replace(",", ".")
    if not raw:
        return True
    if raw in context:
        return True
    # Rounding, as a DECIMAL truncation: 0.05 prefixes 0.0503. Both sides must
    # carry a decimal point, or the bare "0" that every set of session facts
    # contains would vouch for any number beginning with a zero — which is how
    # this first went wrong, and it would have made rule C inert rather than
    # noisy: the quiet failure.
    if "." in raw and any(
            "." in known and (known.startswith(raw) or raw.startswith(known))
            for known in context):
        return True
    try:
        value = float(raw)
    except ValueError:
        return True                     # not a number after all; not our business
    for known in context:
        try:
            other = float(known)
        except ValueError:
            continue
        if percent and (abs(value / 100.0 - other) < 1e-9
                        or abs(value - other * 100.0) < 1e-9):
            return True
        # A rounded quotation of a longer measurement (0.017 written as 0.02),
        # and the reverse. Only against another MEASUREMENT: allowing an integer
        # to vouch within 2% let the bare "1" in every set of session facts
        # excuse a fabricated 0.9999.
        if "." in known and other != 0 and abs(value - other) <= abs(other) * 0.02:
            return True
    return False


def violations(out: dict, results, state: dict, findings: str = "") -> list[Violation]:
    """Everything checkable that is wrong with `out`. Never raises."""
    try:
        say = str((out or {}).get("say") or "")
        shown = f"{findings}\n{_facts(state)}"
        found: list[Violation] = []

        known = _known_files(state or {}, shown)
        for match in _FILE_RE.finditer(say):
            name = match.group(0)
            if name not in known and name.rsplit("/", 1)[-1] not in known:
                found.append(Violation(
                    "B", HARD,
                    f"named '{name}', which this session does not have"))

        context = _numbers(shown)
        for match in _DECIMAL_RE.finditer(say):
            token = match.group(0).strip()
            if not _traceable(token, context):
                found.append(Violation(
                    "C", SOFT,
                    f"gave the measurement {token}, which appears nowhere in the "
                    f"findings or the session facts"))
        return found
    except Exception:                   # noqa: BLE001 — a verifier must not 500
        return []


def has_hard(found) -> bool:
    return any(v.severity == HARD for v in found)


def repair_note(found) -> str:
    """What to tell the director so it can write the answer again, correctly."""
    lines = ["YOUR PREVIOUS REPLY WAS REJECTED BY A CHECK. Write it again, fixing "
             "exactly this and changing nothing else that was true:"]
    lines.extend(f"  - You {v.message}." for v in found)
    lines.append("Say only what the findings above support. If that leaves you with "
                 "less to say, say less.")
    return "\n".join(lines)


def summarise(found) -> str:
    """One line for the transcript, in the artist's terms."""
    return "; ".join(v.message for v in found)
