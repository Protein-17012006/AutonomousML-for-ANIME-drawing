"""Default session repository used by the single-process deployment."""

from service.core.config import max_sessions
from service.sessions.repository import InMemorySessionRepository


default_session_repository = InMemorySessionRepository(cap=max_sessions())
