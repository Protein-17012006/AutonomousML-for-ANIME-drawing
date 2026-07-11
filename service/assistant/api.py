"""Grounded Q&A and agent-chat inbound API adapter."""
from __future__ import annotations

import json
import os
import time

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from service.core.dependencies import get_session_repository
from service.memory.dependencies import memory_store_for
from service.sessions.repository import SessionRepository


router = APIRouter()


class AskReq(BaseModel):
    question: str


class AgentReq(BaseModel):
    message: str = ""
    regenerate: bool = False


_agent_calls: dict[int, list] = {}


def _agent_rate_ok(sid: int) -> bool:
    rpm = int(os.environ.get("COPILOT_AGENT_RPM", "20"))
    now = time.monotonic()
    calls = [called for called in _agent_calls.get(sid, []) if now - called < 60]
    if len(calls) >= rpm:
        _agent_calls[sid] = calls
        return False
    calls.append(now)
    _agent_calls[sid] = calls
    return True


def _user_memories(request: Request):
    user = getattr(request.state, "user", None)
    if user is None:
        return []
    return [
        memory for memory in memory_store_for(request.app).list(user.sub)
        if memory.status == "confirmed"
    ]


@router.post("/session/{sid}/ask")
def post_ask(sid: int, req: AskReq,
             sessions: SessionRepository = Depends(get_session_repository)):
    state = sessions.state_for(sid)
    if state is None:
        raise HTTPException(status_code=404, detail="Unknown session (or no result yet)")
    from service.assistant.ask import answer_question
    from service.infrastructure.director_llm import make_ask_fn
    return answer_question(state, req.question, make_ask_fn())


@router.post("/session/{sid}/agent")
def post_agent(sid: int, req: AgentReq, request: Request,
               sessions: SessionRepository = Depends(get_session_repository)):
    state = sessions.state_for(sid)
    if state is None:
        raise HTTPException(status_code=404, detail="Unknown session (or no result yet)")
    if not _agent_rate_ok(sid):
        raise HTTPException(status_code=429, detail="Agent rate limit reached; retry shortly")
    from service.assistant.agent import append_chat, decide_agent
    from service.infrastructure.director_llm import make_ask_fn

    chat = state.get("chat", [])
    if req.regenerate:
        if chat and chat[-1]["role"] == "assistant":
            chat.pop()
        if not chat or chat[-1]["role"] != "user":
            raise HTTPException(status_code=422, detail="Nothing to regenerate yet")
        output = decide_agent(
            state, chat[-1]["text"], chat[:-1], make_ask_fn(),
            _user_memories(request),
        )
        append_chat(state, "assistant", output["say"])
        return output

    output = decide_agent(
        state, req.message, chat, make_ask_fn(), _user_memories(request))
    append_chat(state, "user", req.message)
    append_chat(state, "assistant", output["say"])
    return output


@router.post("/session/{sid}/agent/stream")
def post_agent_stream(sid: int, req: AgentReq, request: Request,
                      sessions: SessionRepository = Depends(get_session_repository)):
    state = sessions.state_for(sid)
    if state is None:
        raise HTTPException(status_code=404, detail="Unknown session (or no result yet)")
    if not _agent_rate_ok(sid):
        raise HTTPException(status_code=429, detail="Agent rate limit reached; retry shortly")
    from service.assistant.agent import append_chat, decide_agent_stream
    from service.infrastructure.director_llm import make_ask_stream_fn
    memories = _user_memories(request)

    def generate():
        final = None
        for event in decide_agent_stream(
                state, req.message, state.get("chat", []),
                make_ask_stream_fn(), memories):
            if event["event"] == "decision":
                final = event["data"]
            yield (
                f"event: {event['event']}\n"
                f"data: {json.dumps(event['data'], ensure_ascii=False)}\n\n"
            )
        append_chat(state, "user", req.message)
        append_chat(state, "assistant", (final or {}).get("say", ""))

    return StreamingResponse(generate(), media_type="text/event-stream")
