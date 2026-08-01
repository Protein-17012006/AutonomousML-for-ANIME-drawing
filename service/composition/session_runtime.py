"""Concrete wiring for session HTTP ingestion, execution and artifact output."""
from __future__ import annotations

from functools import partial

from service.infrastructure.admission import engine_admission
from service.infrastructure.engines import resolve
from service.infrastructure.publisher import publish_session
from service.media.artifacts import save_pair_mid
from service.media.ingest import _load_frames_from_video, _load_keys, load_image_upload
from service.media.rendering import render_session_artifacts
from service.review.http_dependencies import ReviewHttpRuntime
from service.review.service import ReviewSession
from service.sessions.http_dependencies import SessionHttpRuntime
from service.sessions.repository import SessionRepository
from service.sessions.runner import run_session
from service.sessions.service import RunSession, SessionWorkflowAdapters
from service.sessions.streaming import SessionStreamPorts, stream_session


def build_session_workflow(repository: SessionRepository) -> RunSession:
    """Bind the application use case to concrete outbound adapters."""
    return RunSession(
        repository,
        SessionWorkflowAdapters(
            run_pipeline=run_session,
            save_pair_mid=save_pair_mid,
            render_artifacts=render_session_artifacts,
            publish_session=publish_session,
        ),
    )


def build_session_http_runtime() -> SessionHttpRuntime:
    """Build the one runtime shared by PNG runs, video runs and reruns."""
    ports = SessionStreamPorts(
        resolve_engine=resolve,
        admission_for=engine_admission,
        workflow_for=build_session_workflow,
    )
    return SessionHttpRuntime(
        load_keys=_load_keys,
        load_video_keys=_load_frames_from_video,
        stream_session=partial(stream_session, ports=ports),
    )


def build_review_http_runtime() -> ReviewHttpRuntime:
    """Bind review routes to media and admission adapters in one composition root."""
    return ReviewHttpRuntime(
        review_for=lambda repository: ReviewSession(
            repository, render_session_artifacts),
        load_image=load_image_upload,
        admission_for=engine_admission,
        publish_review=lambda sid, session_dir, outcome, *, owner_sub, pid, workspace_input: publish_session(
            sid, session_dir, outcome, owner_sub=owner_sub, pid=pid,
            workspace_input=workspace_input, update_complete=True),
    )
