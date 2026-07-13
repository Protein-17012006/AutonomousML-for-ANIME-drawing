"""Moved 2026-07-08 → inbetween_copilot.triage.diverse (one-way dependency fix,
architecture review 2026-07-08). This adapter layers CSQ (inbetween_copilot.qa.csq)
over triage aggregates, so it belongs ABOVE benchmark, not inside it.
Shim kept for the archived box drivers (.scratch/triage/revalidate.py); delete
once those migrate."""
from inbetween_copilot.triage.diverse import *  # noqa: F401,F403
