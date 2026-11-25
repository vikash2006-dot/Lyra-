"""Conversational session management for LYRA."""

import time
from typing import Any, Sequence
import uuid

from lyra.core.exceptions import SessionError
from lyra.models.identity import AuthenticationState, User
from lyra.models.messages import Message, Role


class Session:
    """A single conversational session with message history, user identity, and lifecycle timestamps."""

    def __init__(
        self,
        session_id: str | None = None,
        user_id: str = "default_user",
        initial_messages: Sequence[Message] | None = None,
        metadata: dict[str, Any] | None = None,
        auth_state: AuthenticationState = AuthenticationState.ANONYMOUS,
        auth_token: str | None = None,
    ) -> None:
        self.session_id: str = session_id or str(uuid.uuid4())
        self.user_id: str = user_id
        self._messages: list[Message] = list(initial_messages) if initial_messages else []
        self.created_at: float = time.time()
        self.updated_at: float = self.created_at
        self.last_activity: float = self.created_at
        self.auth_state: AuthenticationState = auth_state
        self.auth_token: str | None = auth_token
        self.metadata: dict[str, Any] = dict(metadata) if metadata else {}

    @property
    def is_authenticated(self) -> bool:
        """Check if the session is currently in an authenticated state."""
        return self.auth_state == AuthenticationState.AUTHENTICATED

    def bind_user(self, user: User, auth_token: str | None = None) -> None:
        """Bind an authenticated User identity and optional token to this session."""
        self.user_id = user.id
        self.auth_token = auth_token
        self.auth_state = AuthenticationState.AUTHENTICATED
        self.metadata["username"] = user.username
        self.metadata["display_name"] = user.display_name
        self.touch()

    def logout(self) -> None:
        """Clear authenticated user state and revert to anonymous."""
        self.auth_state = AuthenticationState.ANONYMOUS
        self.auth_token = None
        self.metadata.pop("username", None)
        self.metadata.pop("display_name", None)
        self.touch()

    def touch(self) -> None:
        """Record activity timestamp."""
        now = time.time()
        self.last_activity = now
        self.updated_at = now

    def is_expired(self, max_idle_seconds: float) -> bool:
        """Check if session has been inactive longer than allowed timeout."""
        if max_idle_seconds <= 0:
            return False
        return (time.time() - self.last_activity) > max_idle_seconds

    @property
    def messages(self) -> tuple[Message, ...]:
        """Immutable snapshot of the session's message history."""
        return tuple(self._messages)

    def add_user_message(self, content: str, metadata: dict[str, Any] | None = None) -> Message:
        """Append a user message to the session history."""
        msg = Message(role=Role.USER, content=content, metadata=metadata or {})
        self.add_message(msg)
        return msg

    def add_assistant_message(
        self,
        content: str,
        model: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> Message:
        """Append an assistant response message to the session history."""
        meta = dict(metadata) if metadata else {}
        if model:
            meta["model"] = model
        msg = Message(role=Role.ASSISTANT, content=content, metadata=meta)
        self.add_message(msg)
        return msg

    def add_message(self, message: Message) -> None:
        """Append an arbitrary Message to the session history."""
        if not isinstance(message, Message):
            raise SessionError(f"Cannot append non-Message object: {type(message)}")
        self._messages.append(message)
        self.touch()

    def get_history(self, limit: int | None = None) -> tuple[Message, ...]:
        """Retrieve recent conversation history, optionally bounded by limit."""
        if limit is not None and limit > 0:
            return tuple(self._messages[-limit:])
        return tuple(self._messages)

    def clear(self) -> None:
        """Clear all messages from the session."""
        self._messages.clear()
        self.touch()


class SessionManager:
    """In-memory session registry and factory."""

    def __init__(self) -> None:
        self._sessions: dict[str, Session] = {}

    def create_session(
        self,
        session_id: str | None = None,
        user_id: str = "default_user",
        metadata: dict[str, Any] | None = None,
        auth_state: AuthenticationState = AuthenticationState.ANONYMOUS,
        auth_token: str | None = None,
    ) -> Session:
        """Create and register a new conversation session."""
        session = Session(
            session_id=session_id,
            user_id=user_id,
            metadata=metadata,
            auth_state=auth_state,
            auth_token=auth_token,
        )
        if session.session_id in self._sessions:
            raise SessionError(f"Session with ID '{session.session_id}' already exists.")
        self._sessions[session.session_id] = session
        return session

    def get_session(self, session_id: str) -> Session | None:
        """Retrieve an existing session by ID."""
        return self._sessions.get(session_id)

    def get_or_create_session(
        self,
        session_id: str | None = None,
        user_id: str = "default_user",
        metadata: dict[str, Any] | None = None,
        auth_state: AuthenticationState = AuthenticationState.ANONYMOUS,
        auth_token: str | None = None,
    ) -> Session:
        """Retrieve an existing session or create a new one if not found."""
        if session_id and session_id in self._sessions:
            return self._sessions[session_id]
        return self.create_session(
            session_id=session_id,
            user_id=user_id,
            metadata=metadata,
            auth_state=auth_state,
            auth_token=auth_token,
        )

    def delete_session(self, session_id: str) -> bool:
        """Remove a session from the registry."""
        return self._sessions.pop(session_id, None) is not None

    def list_sessions(self) -> list[Session]:
        """List all active sessions."""
        return list(self._sessions.values())
