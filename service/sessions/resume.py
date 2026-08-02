"""Rebuild a live session from a durable history snapshot.

A `pid` in History is a projection: pair events, a result event, a QA transcript
and PNG/MP4 artifacts. A live `sid` is the runtime object the interactive routes
read — `keys`, `eng`, `cfg`, `result` — held in one process, capped at eight and
gone after a restart. Nothing converted the first into the second, so reopening
a saved session could only ever be read-only.

This restores the artist's INPUTS (the source keys, the configuration) and their
RECORDED DECISIONS (per-pair action, QA verdict, artist verdict), and
regenerates nothing. A re-run would call the VLM again and could return a
different verdict from the one already on the artist's screen; reopening a saved
session must never silently change what it says.

The cost is deliberate and bounded: `PairResult.frames` stays empty, so anything
that needs generated pixels (frame repair) must refuse a resumed session in
words. Submitting a key re-runs the pipeline from `keys` and fills them in — but
that is a new run the artist asked for.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from inbetween_copilot.pipeline.models import CopilotResult, PairResult
from inbetween_copilot.qa.models import FrameQA
from service.sessions.repository import SessionRepository
from service.sessions.schemas import SessionCfg


class NoStoredKeys(Exception):
    """The snapshot carries no source keys, so there is nothing to resume from."""


@dataclass(frozen=True)
class _RestoredRound:
    action_kind: str
    reason: str


@dataclass(frozen=True)
class RestoredCorrection:
    """The correction trace as an OBJECT, not the dict the snapshot stores.

    `PairEvent.from_pair` reads `corr.status` and `round.action_kind`. A resumed
    session is re-projected to pair events on its next render, so handing back a
    bare dict would raise `AttributeError` there instead of here.
    """

    status: str
    keys_used: int
    rounds: list[_RestoredRound]

    @classmethod
    def from_snapshot(cls, value: Any) -> "RestoredCorrection | None":
        if not isinstance(value, dict):
            return None
        rounds = [
            _RestoredRound(
                action_kind=str(entry.get("action") or entry.get("action_kind") or ""),
                reason=str(entry.get("reason") or ""),
            )
            for entry in (value.get("rounds") or [])
            if isinstance(entry, dict)
        ]
        return cls(
            status=str(value.get("status") or ""),
            keys_used=int(value.get("keys_used") or 0),
            rounds=rounds,
        )


def pair_result_from_event(event: dict) -> PairResult:
    """One stored pair event back into the pipeline's own dataclass."""
    status = event.get("qa")
    qa = None
    if status:
        qa = FrameQA(
            status=status,
            reason=event.get("reason") or "",
            p_error=event.get("verdict_prob"),
            u=event.get("uncertainty"),
        )
    return PairResult(
        index=int(event["index"]),
        action=event["action"],
        route=event.get("route"),
        # Deliberately empty: resume restores decisions, never pixels.
        frames=None,
        qa=qa,
        keys_requested=int(event.get("keys_requested") or 0),
        correction=RestoredCorrection.from_snapshot(event.get("correction")),
        triage=event.get("triage"),
        regime=event.get("regime"),
        artist_verdict=event.get("artist_verdict"),
        gap=event.get("gap"),
    )


def result_from_snapshot(pairs: list[dict], result: dict) -> CopilotResult:
    """Rebuild the aggregate exactly as stored.

    The tallies are taken from the stored result rather than recomputed: they are
    what the artist was shown, and recomputing them here would let a future
    change in the aggregation silently rewrite a saved session's history.
    """
    return CopilotResult(
        pairs=[pair_result_from_event(event) for event in pairs],
        keys_requested_total=int(result.get("keys_requested_total") or 0),
        flagged=list(result.get("flagged") or []),
        n_autopass=int(result.get("n_autopass") or 0),
        n_corrected=int(result.get("n_corrected") or 0),
        abstained=list(result.get("abstained") or []),
    )


def cfg_from_snapshot(snapshot: dict, *, default_engines: str) -> SessionCfg:
    """The session's configuration, explicit if stored and derived if not.

    Sessions published before the `resume` block existed still carry
    `result.sampling`, which `build_render_metadata` fills with `cadence_fps`,
    `smoothness`, `output_fps` and `interpolator`. What it never carried —
    `engines`, `tau_gate`, `tau_soft` — falls back to this deployment's current
    values, which is what the session's next run would have used anyway.
    """
    stored = (snapshot.get("resume") or {}).get("cfg")
    if isinstance(stored, dict) and stored:
        return SessionCfg.model_validate(stored)
    sampling = (snapshot.get("result") or {}).get("sampling") or {}
    fields: dict[str, Any] = {"engines": default_engines}
    for source, target in (
        ("cadence_fps", "cadence_fps"),
        ("smoothness", "smoothness"),
        ("output_fps", "fps"),
        ("interpolator", "interpolator"),
    ):
        value = sampling.get(source)
        if value is not None:
            fields[target] = value
    return SessionCfg.model_validate(fields)


def stored_key_names(snapshot: dict) -> list[str]:
    """The source-key filenames in key order — `key_0.png`, `key_1.png`, …

    `render_artifacts` writes these for EVERY flow (the docstring on
    `build_key_frames` claiming otherwise is stale, measured 2026-08-02), so any
    published session has them. Ordering is by the integer index, never by the
    dict's own order: JSON gives no guarantee and `"10"` sorts before `"2"`.
    """
    key_urls = (snapshot.get("result") or {}).get("key_urls") or {}
    ordered = sorted(key_urls.items(), key=lambda item: int(item[0]))
    return [str(name) for _, name in ordered]


class ResumeSession:
    """Install a rebuilt session into the repository under a fresh sid."""

    def __init__(self, repository: SessionRepository, resolve_engine):
        self.repository = repository
        self.resolve_engine = resolve_engine

    def restore(self, pid: str, snapshot: dict, keys: list, *,
                owner_sub: str | None, default_engines: str) -> int:
        if not keys:
            raise NoStoredKeys(
                "this saved session has no stored source keys, so it cannot be resumed"
            )
        cfg = cfg_from_snapshot(snapshot, default_engines=default_engines)
        eng = self.resolve_engine(cfg.engines, interpolator=cfg.interpolator)
        result_event = snapshot.get("result") or {}
        result = result_from_snapshot(snapshot.get("pairs") or [], result_event)

        sid, _ = self.repository.create("copilot_resumed", pin=True)
        try:
            if owner_sub:
                self.repository.set_owner(sid, owner_sub)
            self.repository.save_state(sid, {
                "keys": keys,
                "eng": eng,
                "cfg": cfg,
                "result": result,
                "rev": int((snapshot.get("resume") or {}).get("rev") or 0),
                "explanations": dict(result_event.get("explanations") or {}),
                "qa_degraded": bool(result_event.get("qa_degraded")),
                "sampling": dict(result_event.get("sampling") or {}),
                # Per-gap ground truth is not published (it would mean storing
                # every source frame), so a later re-run of a resumed video
                # session falls back to held-key for the compare artifact.
                "gt_frames": None,
                "published_pid": pid,
                "workspace_input": dict(snapshot.get("upload") or {}),
                # Frame repair reads this: a resumed pair has no frames to paint.
                "resumed": True,
            })
        finally:
            self.repository.unpin(sid)
        return sid
