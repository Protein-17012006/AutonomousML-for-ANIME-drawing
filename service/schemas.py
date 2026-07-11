"""SSE event schemas for the in-between co-pilot service."""
from __future__ import annotations

import os
import re
from typing import Optional

from pydantic import BaseModel, model_validator

# FALLBACK ONLY (P2+D 2026-07-08): FrameQA now carries typed p_error/u fields and
# from_pair prefers them; this regex over the reason string ("csq:… p=… u=…") only
# serves pairs persisted before the typed fields existed. Delete once no stored
# session predates 2026-07-08.
_PU_RE = re.compile(r"p=([0-9.]+).*?u=([0-9.]+)")


class SessionCfg(BaseModel):
    tau_gate: float = 0.017
    tau_soft: float = 0.15
    engines: str = "stub"
    cadence_fps: int = 12      # nominal rate of the artist's keys (on-1s 24 / on-2s 12 / on-3s 8)
    smoothness: int = 2        # display depth: 1 Off / 2 Standard / 4 Extra
    fps: Optional[int] = None  # reconstructed-video playback rate; derived = cadence_fps*smoothness unless passed
    # optional show/series tag — the per-show axis of flag-feedback calibration data
    # (H3). Free-form short string; None = untagged pool.
    show: Optional[str] = None

    @model_validator(mode="after")
    def _derive_fps(self):
        if self.smoothness not in (1, 2, 4):
            raise ValueError(f"smoothness must be 1, 2, or 4 (got {self.smoothness})")
        if self.smoothness == 4 and not os.environ.get("COPILOT_SMOOTHNESS_X4"):
            raise ValueError("smoothness=4 (Extra) is gated; set COPILOT_SMOOTHNESS_X4 after the CSQ probe passes")
        if self.fps is None:
            object.__setattr__(self, "fps", self.cadence_fps * self.smoothness)
        if self.show is not None:
            s = self.show.strip()[:64]
            object.__setattr__(self, "show", s or None)
        return self


class PairEvent(BaseModel):
    index: int
    action: str
    qa: Optional[str] = None
    route: Optional[str] = None
    keys_requested: int
    reason: Optional[str] = None
    verdict_prob: Optional[float] = None    # P(error) from the calibrated QA (for a confidence meter)
    uncertainty: Optional[float] = None     # CSQ uncertainty u
    mid_url: Optional[str] = None   # in-between PNG url, streamed live per pair
    # correction-loop trace {status, keys_used, rounds:[{action, reason}]} — the
    # director's visible decisions (vault 'DeepSeek Director Wiring'). None when
    # the pair never entered the loop.
    correction: Optional[dict] = None
    # wide-gap diagnosis for gate-refused pairs (ADR-0015):
    # {cls, keys_suggested, confidence, evidence, brief}. None for filled pairs.
    triage: Optional[dict] = None

    @classmethod
    def from_pair(cls, pair, mid_url: Optional[str] = None) -> "PairEvent":
        qa_status = pair.qa.status if pair.qa is not None else None
        reason = pair.qa.reason if pair.qa is not None else None
        # typed fields first; regex over the note only as legacy fallback
        p_err = getattr(pair.qa, "p_error", None) if pair.qa is not None else None
        u = getattr(pair.qa, "u", None) if pair.qa is not None else None
        if p_err is None and reason:
            m = _PU_RE.search(reason)
            if m:
                p_err, u = float(m.group(1)), float(m.group(2))
        corr = getattr(pair, "correction", None)
        correction = None
        if corr is not None:
            correction = {
                "status": corr.status,
                "keys_used": corr.keys_used,
                "rounds": [{"action": r.action_kind,
                            "reason": getattr(r, "reason", "")} for r in corr.rounds],
            }
        return cls(
            index=pair.index,
            action=pair.action,
            qa=qa_status,
            route=pair.route,
            keys_requested=pair.keys_requested,
            reason=reason,
            verdict_prob=p_err,
            uncertainty=u,
            mid_url=mid_url,
            correction=correction,
            triage=getattr(pair, "triage", None),
        )


class ResultEvent(BaseModel):
    n_autopass: int
    n_corrected: int
    keys_requested_total: int
    flagged: list
    abstained: list
    needs_key: list
    artifacts: dict
    explanations: dict = {}
    pair_mids: dict = {}   # {pair_index(str): in-between PNG url} for the per-pair line-test
    # {key_index(str): key PNG url}. Only populated for the drop-a-video flow (keys decoded
    # server-side); for PNG upload the client already has object URLs so this stays empty.
    key_urls: dict = {}
    # drop-a-video decimation summary {source_frames, requested_stride, stride, kept} so the UI
    # can show "kept K of N frames (every S-th)" and flag a coarse auto-fit. None for PNG upload.
    sampling: Optional[dict] = None
    # calibrated abstain band for the confidence dial: {tau_pass, tau_flag, u_edges, u_max}
    # (per-u-bin thresholds on p_error). None when no CSQ calibrator is wired (e.g. stub engines).
    csq: Optional[dict] = None
    # True when the served VLM was unreachable during the run: QA degraded to the
    # softness/gate signals only — verdicts are NOT the full calibrated QA (audit
    # 2026-07-02 finding #6: the failure used to be invisible to the client).
    qa_degraded: bool = False

    @classmethod
    def from_result(cls, result, artifacts: dict = None, explanations: dict = None,
                    pair_mids: dict = None, csq: dict = None, key_urls: dict = None,
                    sampling: dict = None, qa_degraded: bool = False) -> "ResultEvent":
        if artifacts is None:
            artifacts = {}
        if explanations is None:
            explanations = {}
        if pair_mids is None:
            pair_mids = {}
        if key_urls is None:
            key_urls = {}
        needs_key = [p.index for p in result.pairs if p.action == "needs_key"]
        return cls(
            n_autopass=result.n_autopass,
            n_corrected=result.n_corrected,
            keys_requested_total=result.keys_requested_total,
            flagged=result.flagged,
            abstained=result.abstained,
            needs_key=needs_key,
            artifacts=artifacts,
            explanations=explanations,
            pair_mids=pair_mids,
            key_urls=key_urls,
            sampling=sampling,
            csq=csq,
            qa_degraded=qa_degraded,
        )


class ErrorEvent(BaseModel):
    message: str


def sse(name: str, model) -> str:
    return f"event: {name}\ndata: {model.model_dump_json()}\n\n"
