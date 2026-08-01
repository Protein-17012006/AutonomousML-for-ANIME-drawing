"""Session-scoped agent-to-agent transcript: capped, JSON-safe, renderable.

Stored as plain dicts (not dataclasses) so a durable session repository can
serialise state without knowing this package exists.
"""
from __future__ import annotations

from service.orchestration.models import MAX_TRANSCRIPT_ENTRIES

_KEY = "transcript"


def entries_for(state: dict) -> list:
    entries = state.get(_KEY)
    return entries if isinstance(entries, list) else []


def append_entries(state: dict, entries) -> None:
    """Append TranscriptEntry objects (or dicts); oldest fall off at the cap."""
    log = list(entries_for(state))
    for entry in entries:
        log.append(entry if isinstance(entry, dict) else entry.as_dict())
    del log[:-MAX_TRANSCRIPT_ENTRIES]
    state[_KEY] = log


def render_markdown(entries) -> str:
    """One table for the exported bundle and the report.

    The from/to pair is rendered as a single "a → b" cell rather than two columns:
    the deliverable is a record of WHO ASKED WHOM, and an arrow reads as a
    conversation where two adjacent columns read as a log."""
    rows = ["| # | conversation | kind | ms | message |",
            "|---|--------------|------|---:|---------|"]
    for e in entries:
        text = str(e.get("text", "")).replace("|", "\\|").replace("\n", " ")
        rows.append(
            f"| {e.get('seq', '')} | {e.get('frm', '')} → {e.get('to', '')} "
            f"| {e.get('kind', '')} | {e.get('ms', 0)} | {text} |")
    if len(rows) == 2:
        rows.append("| | | | | *(no agent conversation recorded)* |")
    return "# Agent conversation\n\n" + "\n".join(rows) + "\n"
