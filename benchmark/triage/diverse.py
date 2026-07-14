"""Moved 2026-07-14 → inbetween_copilot.infrastructure.benchmark_triage,
architecture review 2026-07-08). This adapter layers CSQ (inbetween_copilot.qa.csq)
over triage aggregates, so it belongs ABOVE benchmark, not inside it.
Shim kept for the archived box drivers (.scratch/triage/revalidate.py); delete
once those migrate."""
from inbetween_copilot.infrastructure.benchmark_triage import *  # noqa: F401,F403
