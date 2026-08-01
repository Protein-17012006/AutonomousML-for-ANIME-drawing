"""Late binding: a step's args may name an earlier step's answer.

Pure — no I/O, and no imports outside this package. A reference that cannot be
resolved is NEVER passed through as its literal string; the caller turns it into
a `rejected` step carrying the reason, which is the rail an invalid tool argument
already travels. Fail-closed has one consequence worth knowing: an artist who
genuinely types "$1.foo" into a memory value gets that step refused rather than
stored verbatim. Rare, and it fails safe.
"""
from __future__ import annotations

import re

REFERENCE = re.compile(r"^\$([1-9]\d*)\.([a-z_][a-z0-9_]*)$")

_SCALAR = (bool, int, float, str)


def is_reference(value) -> bool:
    return isinstance(value, str) and REFERENCE.match(value) is not None


def resolve_args(args, sources) -> tuple:
    """Resolve every reference in `args` against steps that have already run.

    `sources` maps step id -> {"kind", "payload"} and holds ONLY finished steps,
    so a forward reference and a step that never ran are refused identically.

    Returns (resolved, bound, error):
      resolved  the new args dict, or None when anything failed
      bound     {arg_key: reference} — the transcript renders this
      error     "" when fine, else why the step must be rejected
    """
    if not isinstance(args, dict):
        return {}, {}, ""
    sources = sources or {}
    resolved: dict = {}
    bound: dict = {}
    for key, value in args.items():
        match = REFERENCE.match(value) if isinstance(value, str) else None
        if match is None:
            resolved[key] = value
            continue
        step_id, field = int(match.group(1)), match.group(2)
        source = sources.get(step_id)
        if source is None:
            return None, bound, (
                f"{value} refers to step {step_id}, which has not run — a step may "
                "only read an EARLIER step's answer.")
        if source.get("kind") != "agent":
            return None, bound, (
                f"{value} refers to step {step_id}, which is a tool. A tool "
                "produces no finding to read.")
        payload = source.get("payload") or {}
        if field not in payload:
            reported = ", ".join(sorted(payload)) or "(nothing)"
            return None, bound, (
                f"{value} asks step {step_id} for '{field}', which it did not "
                f"report. It reported: {reported}.")
        found = payload[field]
        if not isinstance(found, _SCALAR):
            return None, bound, (
                f"{value} resolved to a {type(found).__name__}, not a single value.")
        resolved[key] = found
        bound[key] = value
    return resolved, bound, ""
