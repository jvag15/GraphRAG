# src/api/conversation_manager.py
"""
In-memory multi-turn conversation history per session.
"""

from dataclasses import dataclass, field
from datetime import datetime
import uuid


@dataclass
class Turn:
    role: str           # "user" | "assistant"
    content: str
    sources: list[dict] # list of {chunk_id, document, section} for assistant turns
    timestamp: datetime = field(default_factory=datetime.now)


@dataclass
class Session:
    session_id: str
    turns: list[Turn] = field(default_factory=list)
    created_at: datetime = field(default_factory=datetime.now)
    last_active: datetime = field(default_factory=datetime.now)


class ConversationManager:
    def __init__(self, max_sessions: int = 100, max_turns_per_session: int = 50):
        self._sessions: dict[str, Session] = {}
        self.max_sessions = max_sessions
        self.max_turns_per_session = max_turns_per_session

    def create_session(self) -> str:
        session_id = str(uuid.uuid4())[:8]
        self._sessions[session_id] = Session(session_id=session_id)
        return session_id

    def get_session(self, session_id: str) -> Session | None:
        return self._sessions.get(session_id)

    def add_turn(self, session_id: str, role: str, content: str, sources: list = None):
        session = self._sessions.get(session_id)
        if not session:
            return
        session.turns.append(Turn(role=role, content=content, sources=sources or []))
        session.last_active = datetime.now()
        # Trim if too long
        if len(session.turns) > self.max_turns_per_session:
            session.turns = session.turns[-self.max_turns_per_session:]

    def get_history_for_llm(self, session_id: str) -> list[dict]:
        """Return conversation history in llama-cpp messages format."""
        session = self._sessions.get(session_id)
        if not session:
            return []
        return [{"role": t.role, "content": t.content} for t in session.turns]

    def get_summary(self, session_id: str) -> str:
        """Return brief summary of conversation so far for query router context."""
        session = self._sessions.get(session_id)
        if not session or not session.turns:
            return "No prior conversation."
        recent = session.turns[-4:]  # last 2 exchanges
        lines = [f"{t.role.upper()}: {t.content[:200]}" for t in recent]
        return "\n".join(lines)

    def delete_session(self, session_id: str):
        self._sessions.pop(session_id, None)