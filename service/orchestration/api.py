"""Inbound SSE adapter for the orchestrated goal use case.

Additive: POST /session/{sid}/agent/stream is untouched and keeps its behaviour.
"""
from __future__ import annotations

import json

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse

from service.assistant.api import (AgentReq, _agent_rate_ok,
                                   _state_with_private_chat, _user_memories,
                                   record_turn)
from service.session_history.dependencies import get_optional_history_transcripts
from service.infrastructure.director_llm import make_ask_fn
from service.orchestration.service import run_goal_stream
from service.sessions.http_dependencies import get_session_repository
from service.sessions.repository import SessionRepository

router = APIRouter()


def _sse(name: str, payload) -> str:
    return f"event: {name}\ndata: {json.dumps(payload, ensure_ascii=False)}\n\n"


@router.post("/session/{sid}/orchestrate/stream")
def post_orchestrate_stream(
        sid: int, req: AgentReq, request: Request,
        sessions: SessionRepository = Depends(get_session_repository),
        transcripts=Depends(get_optional_history_transcripts)):
    stored = sessions.state_for(sid)
    if stored is None:
        raise HTTPException(status_code=404,
                            detail="Unknown session (or no result yet)")
    if not _agent_rate_ok(request, sid):
        raise HTTPException(status_code=429,
                            detail="Agent rate limit reached; retry shortly")

    memories = _user_memories(request)
    state = _state_with_private_chat(stored)
    history = list(state["chat"])
    message = req.message

    def generate():
        # Each utterance leaves the server as it happens — the transcript is live,
        # not a recording replayed after the turn finishes.
        output = {}
        # Kept as well as streamed: this exchange — planner to triage, triage to
        # perception — is the evidence that the agents cooperated, and until now
        # it existed only in the browser that watched it go past.
        entries = []
        for kind, payload in run_goal_stream(
                state, message, history,
                plan_ask_fn=make_ask_fn(), say_ask_fn=make_ask_fn(),
                memories=memories):
            if kind == "agent":
                entries.append(payload.as_dict())
                yield _sse("agent", payload.as_dict())
            else:
                output = payload
        yield _sse("say", output.get("say", ""))

        try:
            with sessions.session_transaction(sid):
                latest = sessions.state_for(sid)
                if latest is None:
                    raise KeyError(sid)
                updated = _state_with_private_chat(latest)
                updated["transcript"] = state.get("transcript", [])
                from service.assistant.agent import append_chat
                append_chat(updated, "user", message)
                append_chat(updated, "assistant", output.get("say", ""))
                sessions.save_state(sid, updated)
        except Exception:
            yield _sse("error", {"message": "could not persist chat; retry"})
            return

        record_turn(transcripts, updated, message, output,
                    owner_sub=sessions.owner_for(sid), entries=entries)
        yield _sse("decision", output)

    return StreamingResponse(generate(), media_type="text/event-stream")
