"""Framework-independent session application service.

The service owns the run use case.  FastAPI/SSE is an inbound adapter and the
renderer, publisher, engine and repository are outbound ports supplied by the
composition layer.
"""
from __future__ import annotations

import copy
from dataclasses import dataclass, field as dataclasses_field
from typing import Any, Callable

from service.sessions.presentation import build_render_metadata
from service.sessions.repository import SessionRepository


@dataclass(frozen=True)
class SessionWorkflowAdapters:
    run_pipeline: Callable
    save_pair_mid: Callable
    render_artifacts: Callable
    publish_session: Callable


@dataclass
class SessionOutcome:
    result: Any
    # the session this outcome belongs to, so clients never have to recover it by
    # parsing an artifact URL (a published session re-serves those under a
    # different prefix, which silently yielded no id and killed grounded Q&A)
    sid: int
    artifact_urls: dict
    explanations: dict
    pair_mids: dict
    key_urls: dict
    sampling: dict
    csq: dict | None
    qa_degraded: bool
    # The session's own configuration and revision, carried so the publisher can
    # write a resume block. `sampling` records cadence/smoothness/fps but never
    # `engines` or the taus, and without those a reopened session cannot be
    # rebuilt into a working one. Optional: not every producer of an outcome has
    # them, and a missing block only costs the resume path a derivation.
    # Overlay urls for GATE-REFUSED pairs (see RenderMetadata.pair_keys).
    # Defaulted and last: SessionOutcome is built positionally elsewhere, so a
    # field inserted mid-list silently shifts every argument after it.
    pair_keys: dict = dataclasses_field(default_factory=dict)
    cfg: Any = None
    rev: int = 0


class RunSession:
    def __init__(self, repository: SessionRepository, adapters: SessionWorkflowAdapters):
        self.repository = repository
        self.adapters = adapters

    def execute(self, sid: int, session_dir: str, key_arrays: list, eng, cfg,
                *, sampling: dict | None, emit_pair: Callable,
                gt_frames: list | None = None) -> SessionOutcome:
        a = self.adapters

        def on_pair(pair):
            mid_fn = a.save_pair_mid(pair, session_dir)
            mid_url = f"/session/{sid}/{mid_fn}" if mid_fn else None
            emit_pair(pair, mid_url)

        result = a.run_pipeline(key_arrays, eng, on_pair=on_pair, cfg=cfg)
        rendered = a.render_artifacts(
            result,
            key_arrays,
            session_dir,
            cadence_fps=cfg.cadence_fps,
            smoothness=cfg.smoothness,
            output_fps=cfg.fps,
            mid_engine=eng.rife_engine,
            vlm_struct_fn=eng.vlm_struct_fn,
            softness_fn=eng.softness_fn,
            gt_frames=gt_frames,
        )
        metadata = build_render_metadata(
            sid, rendered, cfg, eng, base_sampling=sampling)
        persisted_explanations = copy.deepcopy(metadata.explanations)
        persisted_sampling = dict(metadata.sampling)
        self.repository.save_state(sid, {
            "keys": key_arrays,
            "eng": eng,
            "cfg": cfg,
            "result": result,
            "rev": 0,
            "explanations": persisted_explanations,
            # The key-travel overlay for each GATE-REFUSED pair. It was returned
            # to the client and never persisted, so no agent could see it: asked
            # "where in the image?", triage answered "there is nothing to point
            # at" while pair_1_keys.png sat in this very directory.
            "pair_keys": dict(metadata.pair_keys or {}),
            # The rendered in-between for each FILLED pair, and the same trap one
            # line up: it was returned to the client and never persisted, so
            # `_valid_repairable` — which reads state["pair_mids"], and whose only
            # other source `PairResult.mid_url` does not exist as a field — was
            # False for every pair of every session. `image_edit` could be
            # proposed by the agent and was refused by the server, always.
            "pair_mids": dict(metadata.pair_mids or {}),
            "qa_degraded": metadata.qa_degraded,
            "sampling": persisted_sampling,
            # per-gap real GT (video flow; None for PNG uploads) — the compare
            # artifact's ORIGINAL pane on review re-renders
            "gt_frames": gt_frames,
        })
        return SessionOutcome(
            result=result,
            sid=sid,
            artifact_urls=metadata.artifact_urls,
            explanations=metadata.explanations,
            pair_mids=metadata.pair_mids,
            key_urls=metadata.key_urls,
            pair_keys=metadata.pair_keys,
            sampling=metadata.sampling,
            csq=metadata.csq,
            qa_degraded=metadata.qa_degraded,
            cfg=cfg,
            rev=0,
        )

    def publish(
        self,
        sid: int,
        session_dir: str,
        outcome: SessionOutcome,
        *,
        history_pid: str | None = None,
        workspace_input: dict | None = None,
    ) -> dict:
        return self.adapters.publish_session(
            sid, session_dir, outcome,
            owner_sub=self.repository.owner_for(sid),
            pid=history_pid,
            workspace_input=workspace_input,
        ) or {}
