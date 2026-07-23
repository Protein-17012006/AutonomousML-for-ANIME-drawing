"""Framework-independent session application service.

The service owns the run use case.  FastAPI/SSE is an inbound adapter and the
renderer, publisher, engine and repository are outbound ports supplied by the
composition layer.
"""
from __future__ import annotations

import copy
from dataclasses import dataclass
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
    artifact_urls: dict
    explanations: dict
    pair_mids: dict
    key_urls: dict
    sampling: dict
    csq: dict | None
    qa_degraded: bool


class RunSession:
    def __init__(self, repository: SessionRepository, adapters: SessionWorkflowAdapters):
        self.repository = repository
        self.adapters = adapters

    def execute(self, sid: int, session_dir: str, key_arrays: list, eng, cfg,
                *, sampling: dict | None, emit_pair: Callable) -> SessionOutcome:
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
            "qa_degraded": metadata.qa_degraded,
            "sampling": persisted_sampling,
        })
        return SessionOutcome(
            result=result,
            artifact_urls=metadata.artifact_urls,
            explanations=metadata.explanations,
            pair_mids=metadata.pair_mids,
            key_urls=metadata.key_urls,
            sampling=metadata.sampling,
            csq=metadata.csq,
            qa_degraded=metadata.qa_degraded,
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
