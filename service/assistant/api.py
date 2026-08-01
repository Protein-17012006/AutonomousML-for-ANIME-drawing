"""Grounded Q&A and agent-chat inbound API adapter."""
from __future__ import annotations

from collections import deque
import json
import threading
import time

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from service.core.auth import CurrentUser, require_current_user
from service.core.config import AgentRateLimitSettings
from service.memory.dependencies import memory_store_for
from service.session_history.adapters import TranscriptStoreError
from service.session_history.dependencies import get_history_transcripts
from service.sessions.repository import SessionRepository
from service.sessions.http_dependencies import get_session_repository


router = APIRouter()


class AskReq(BaseModel):
    question: str


class AgentReq(BaseModel):
    message: str = ""
    regenerate: bool = False


class AgentRateLimiter:
    """Thread-safe sliding-window limiter with TTL cleanup and a hard bucket cap."""

    def __init__(self, *, clock=time.monotonic, window_seconds: float = 60.0):
        self._clock = clock
        self._window_seconds = window_seconds
        self._calls: dict[int, deque[float]] = {}
        self._lock = threading.Lock()

    def allow(self, sid: int, *, rpm: int, max_buckets: int) -> bool:
        now = self._clock()
        cutoff = now - self._window_seconds
        with self._lock:
            # Expire abandoned session buckets, not only the bucket being hit.
            for key, calls in list(self._calls.items()):
                while calls and calls[0] <= cutoff:
                    calls.popleft()
                if not calls:
                    del self._calls[key]

            if sid not in self._calls and len(self._calls) >= max_buckets:
                oldest = min(
                    self._calls,
                    key=lambda key: self._calls[key][-1],
                )
                del self._calls[oldest]

            calls = self._calls.setdefault(sid, deque())
            if len(calls) >= rpm:
                return False
            calls.append(now)
            return True

    @property
    def bucket_count(self) -> int:
        with self._lock:
            return len(self._calls)


class _ChatPersistenceConflict(Exception):
    """The streamed reply no longer matches the latest conversation tail."""


_limiter_init_lock = threading.Lock()


def _agent_limiter_for(app) -> AgentRateLimiter:
    limiter = getattr(app.state, "agent_rate_limiter", None)
    if limiter is None:
        with _limiter_init_lock:
            limiter = getattr(app.state, "agent_rate_limiter", None)
            if limiter is None:
                limiter = AgentRateLimiter()
                app.state.agent_rate_limiter = limiter
    return limiter


def _agent_rate_ok(request: Request, sid: int) -> bool:
    settings = AgentRateLimitSettings.from_env()
    return _agent_limiter_for(request.app).allow(
        sid,
        rpm=settings.requests_per_minute,
        max_buckets=settings.max_buckets,
    )


def _user_memories(request: Request):
    user = getattr(request.state, "user", None)
    if user is None:
        return []
    return [
        memory for memory in memory_store_for(request.app).list(user.sub)
        if memory.status == "confirmed"
    ]


def _state_with_private_chat(state: dict) -> dict:
    """Copy the mutable chat portion before changing repository state."""
    copied = dict(state)
    copied["chat"] = [dict(turn) for turn in state.get("chat", [])]
    return copied


@router.post("/session/{sid}/ask")
def post_ask(
    sid: int,
    req: AskReq,
    user: CurrentUser = Depends(require_current_user),
    sessions: SessionRepository = Depends(get_session_repository),
    transcripts=Depends(get_history_transcripts),
):
    state = sessions.state_for(sid)
    if state is None:
        raise HTTPException(status_code=404, detail="Unknown session (or no result yet)")
    pid = state.get("published_pid")
    if not isinstance(pid, str) or not pid:
        raise HTTPException(status_code=409, detail="Session is still being saved")
    from service.assistant.ask import answer_question
    from service.infrastructure.director_llm import make_ask_fn
    answer = answer_question(state, req.question, make_ask_fn())
    try:
        turn = transcripts.append_turn(
            pid,
            user.sub,
            question=req.question,
            answer=answer["answer"],
            grounded=answer["grounded"],
        )
    except TranscriptStoreError as exc:
        raise HTTPException(status_code=503, detail="Could not save Q&A; retry") from exc
    return {**answer, "turn": turn.model_dump()}


@router.post("/session/{sid}/agent")
def post_agent(sid: int, req: AgentReq, request: Request,
               sessions: SessionRepository = Depends(get_session_repository)):
    if sessions.state_for(sid) is None:
        raise HTTPException(status_code=404, detail="Unknown session (or no result yet)")
    if not _agent_rate_ok(request, sid):
        raise HTTPException(status_code=429, detail="Agent rate limit reached; retry shortly")
    from service.assistant.agent import append_chat, decide_agent
    from service.infrastructure.director_llm import make_ask_fn

    try:
        with sessions.session_transaction(sid):
            stored = sessions.state_for(sid)
            if stored is None:
                raise HTTPException(
                    status_code=404, detail="Unknown session (or no result yet)")
            state = _state_with_private_chat(stored)
            chat = state["chat"]
            if req.regenerate:
                if chat and chat[-1]["role"] == "assistant":
                    chat.pop()
                if not chat or chat[-1]["role"] != "user":
                    raise HTTPException(
                        status_code=422, detail="Nothing to regenerate yet")
                output = decide_agent(
                    state, chat[-1]["text"], chat[:-1], make_ask_fn(),
                    _user_memories(request),
                )
                append_chat(state, "assistant", output["say"])
                sessions.save_state(sid, state)
                return output

            output = decide_agent(
                state, req.message, chat, make_ask_fn(), _user_memories(request))
            append_chat(state, "user", req.message)
            append_chat(state, "assistant", output["say"])
            sessions.save_state(sid, state)
            return output
    except KeyError as exc:
        raise HTTPException(
            status_code=404, detail="Unknown session (or no result yet)") from exc


@router.post("/session/{sid}/agent/stream")
def post_agent_stream(sid: int, req: AgentReq, request: Request,
                      sessions: SessionRepository = Depends(get_session_repository)):
    stored = sessions.state_for(sid)
    if stored is None:
        raise HTTPException(status_code=404, detail="Unknown session (or no result yet)")
    if not _agent_rate_ok(request, sid):
        raise HTTPException(status_code=429, detail="Agent rate limit reached; retry shortly")
    from service.assistant.agent import append_chat, decide_agent_stream
    from service.infrastructure.director_llm import make_ask_stream_fn
    memories = _user_memories(request)
    state = _state_with_private_chat(stored)
    original_chat = [dict(turn) for turn in state["chat"]]
    message = req.message
    history = state["chat"]
    if req.regenerate:
        if history and history[-1]["role"] == "assistant":
            history.pop()
        if not history or history[-1]["role"] != "user":
            raise HTTPException(status_code=422, detail="Nothing to regenerate yet")
        message = history[-1]["text"]
        history = history[:-1]

    def generate():
        final = None
        decision_event = None
        for event in decide_agent_stream(
                state, message, history,
                make_ask_stream_fn(), memories):
            if event["event"] == "decision":
                final = event["data"]
                decision_event = event
                # A decision is the success boundary. Hold it until the chat
                # transaction commits so the client never sees success for a
                # reply that a durable repository failed to persist.
                continue
            yield (
                f"event: {event['event']}\n"
                f"data: {json.dumps(event['data'], ensure_ascii=False)}\n\n"
            )
        # Merge the completed turn into the latest state under the repository's
        # per-session transaction. This avoids depending on the current RAM
        # adapter returning a live mutable dictionary and prevents lost writes
        # when a durable repository is introduced.
        try:
            with sessions.session_transaction(sid):
                latest = sessions.state_for(sid)
                if latest is None:
                    raise _ChatPersistenceConflict()
                updated = _state_with_private_chat(latest)
                if req.regenerate:
                    # Replace only the reply we actually regenerated. If another
                    # request changed the conversation while this SSE was in
                    # flight, leave that newer history intact instead of deleting
                    # a turn based on a stale snapshot.
                    if updated["chat"] != original_chat:
                        raise _ChatPersistenceConflict()
                    if updated["chat"] and updated["chat"][-1]["role"] == "assistant":
                        updated["chat"].pop()
                else:
                    append_chat(updated, "user", message)
                append_chat(updated, "assistant", (final or {}).get("say", ""))
                sessions.save_state(sid, updated)
        except (KeyError, _ChatPersistenceConflict):
            yield (
                "event: error\n"
                "data: {\"message\": \"conversation changed; retry\"}\n\n"
            )
            return
        except Exception:
            yield (
                "event: error\n"
                "data: {\"message\": \"could not persist chat; retry\"}\n\n"
            )
            return

        if decision_event is not None:
            yield (
                f"event: {decision_event['event']}\n"
                f"data: {json.dumps(decision_event['data'], ensure_ascii=False)}\n\n"
            )

    return StreamingResponse(generate(), media_type="text/event-stream")
