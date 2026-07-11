"""Flag-feedback domain: one artist vote + a machine-verdict snapshot per record.

The artist votes ONCE, on clip quality ("this in-between looks fine / wrong").
The machine side (CSQ decision, p_error, u, error_type/region, session config)
is snapshotted at vote time, so a single record carries both labels and
agreement stays derivable (vote=down & qa=pass -> candidate pass_miss;
vote=up & qa=flag -> candidate false positive). This is per-show CSQ
calibration data, not analytics (design note 2026-07-11)."""
from __future__ import annotations

import time
from typing import Literal, Optional

from pydantic import BaseModel

Vote = Literal["up", "down"]


class FeedbackRecord(BaseModel):
    # identity
    sid: int
    pair_index: int
    voter: str                    # Cognito User-Pool sub, or "anon"
    # human side
    vote: Vote
    ts: int                       # epoch millis at vote time
    # machine snapshot (survives session eviction — never re-joinable later)
    qa_status: Optional[str] = None
    p_error: Optional[float] = None
    u: Optional[float] = None
    route: Optional[str] = None
    action: Optional[str] = None
    error_type: Optional[str] = None
    region: Optional[str] = None
    engines: Optional[str] = None
    cadence_fps: Optional[int] = None
    smoothness: Optional[int] = None
    show: Optional[str] = None
    qa_degraded: bool = False
    rev: Optional[int] = None      # draw-key correction pass this snapshot was taken at


def build_feedback(state: dict, sid: int, pair_index: int, vote: str,
                   voter: str) -> FeedbackRecord:
    """Snapshot the machine verdict for `pair_index` and attach the vote.

    Raises ValueError on an unknown pair, a non-votable `needs_key` pair
    (no interpolated clip exists to rate), or a bad vote value."""
    if vote not in ("up", "down"):
        raise ValueError(f"vote must be 'up' or 'down' (got {vote!r})")
    pairs = state["result"].pairs
    if not 0 <= pair_index < len(pairs):
        raise ValueError(f"pair_index out of range 0..{len(pairs) - 1}")
    pair = pairs[pair_index]
    if pair.action == "needs_key":
        raise ValueError("needs_key pair has no in-between to rate")
    qa = pair.qa
    exp = (state.get("explanations") or {}).get(pair_index) or {}
    cfg = state.get("cfg")
    rev = state.get("rev")
    rev = rev if isinstance(rev, int) else None
    return FeedbackRecord(
        sid=sid, pair_index=pair_index, voter=voter, vote=vote,
        ts=int(time.time() * 1000),
        qa_status=qa.status if qa is not None else None,
        p_error=getattr(qa, "p_error", None) if qa is not None else None,
        u=getattr(qa, "u", None) if qa is not None else None,
        route=pair.route, action=pair.action,
        error_type=exp.get("err_type"), region=exp.get("region"),
        engines=getattr(cfg, "engines", None),
        cadence_fps=getattr(cfg, "cadence_fps", None),
        smoothness=getattr(cfg, "smoothness", None),
        show=getattr(cfg, "show", None),
        qa_degraded=bool(state.get("qa_degraded")),
        rev=rev,
    )
