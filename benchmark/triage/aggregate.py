"""U3 -- the aggregator. Auto-labels ONLY unanimous-clean clips (trust-first: errors
are never auto-asserted from orthogonal lenses that share blind spots); everything
with a flag, an unsure, or a fired styl_guard becomes a disagreement for the Claude
pass. Pure + deterministic."""
from __future__ import annotations

from dataclasses import dataclass

POSITIVE = ["gap", "timing", "identity", "lineart", "morph"]
N_LENSES = 6


@dataclass(frozen=True)
class ClipTriage:
    clip: str
    decision: str          # "auto_clean" | "disagree"
    lens_votes: dict
    n_flag: int
    n_unsure: int
    styl: bool
    disagreement: float


def _v(lens_votes, key):
    return lens_votes.get(key, {"verdict": "unsure", "note": ""}).get("verdict", "unsure")


def aggregate(clip: str, lens_votes: dict) -> ClipTriage:
    pos = [_v(lens_votes, k) for k in POSITIVE]
    n_flag = sum(1 for v in pos if v == "flag")
    n_unsure = sum(1 for k in [*POSITIVE, "styl_guard"] if _v(lens_votes, k) == "unsure")
    styl = _v(lens_votes, "styl_guard") == "flag"
    auto_clean = all(v == "clean" for v in pos) and n_unsure == 0 and not styl
    decision = "auto_clean" if auto_clean else "disagree"
    flag_frac = n_flag / len(POSITIVE)
    styl_conflict = 1.0 if (styl and n_flag > 0) else 0.0
    disagreement = 0.5 * flag_frac + 0.5 * (n_unsure / N_LENSES) + styl_conflict
    return ClipTriage(clip, decision, lens_votes, n_flag, n_unsure, styl, float(disagreement))
