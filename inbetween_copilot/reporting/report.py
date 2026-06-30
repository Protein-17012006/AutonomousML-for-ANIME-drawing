"""Artist-facing co-pilot report -- the "draw less + auto-fix" headline.

drew N keys -> received M in-betweens -> X% auto-passed clean, A auto-corrected
by the loop, Y still need review, plus the count of extra breakdown keys the
gate asked the artist to draw.
"""
from __future__ import annotations

from dataclasses import dataclass

from inbetween_copilot.pipeline.copilot import CopilotResult


@dataclass
class CopilotReport:
    keys_drawn: int
    inbetweens_made: int
    n_autopass: int
    n_corrected: int
    n_flagged: int
    auto_pass_rate: float
    flag_rate: float
    keys_requested: int
    summary: str


def summarize(result: CopilotResult, keys_drawn: int) -> CopilotReport:
    made = sum(1 for p in result.pairs if p.frames is not None)
    n_flagged = len(result.flagged)
    apr = (result.n_autopass / made) if made else 0.0
    fr = (n_flagged / made) if made else 0.0
    summary = (f"drew {keys_drawn} keys -> {made} in-betweens -> "
               f"{apr:.0%} auto-pass, {result.n_corrected} auto-corrected, "
               f"{n_flagged} to review; "
               f"{result.keys_requested_total} extra key(s) requested")
    return CopilotReport(keys_drawn=keys_drawn, inbetweens_made=made,
                         n_autopass=result.n_autopass, n_corrected=result.n_corrected,
                         n_flagged=n_flagged, auto_pass_rate=apr, flag_rate=fr,
                         keys_requested=result.keys_requested_total, summary=summary)
