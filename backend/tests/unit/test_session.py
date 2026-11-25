"""Unit tests for LYRA conversational session management."""

import time
import pytest

from lyra.companion.session import Session, SessionManager
from lyra.core.exceptions import SessionError
from lyra.models.messages import Message, Role


def test_session_initialization() -> None:
    """Verify session creation and initial timestamp state."""
    session = Session(session_id="test-session-1")
    assert session.session_id == "test-session-1"
    assert len(session.messages) == 0
    assert session.created_at > 0
    assert session.updated_at == session.created_at


def test_session_add_messages() -> None:
    """Verify adding user and assistant messages updates history and updated_at."""
    session = Session()
    start_time = session.updated_at

    time.sleep(0.01)
    user_msg = session.add_user_message("Hello LYRA")
    assert user_msg.role == Role.USER
    assert user_msg.content == "Hello LYRA"
    assert len(session.messages) == 1
    assert session.updated_at >= start_time

    asst_msg = session.add_assistant_message("Hello! How can I help?", model="mock-llm")
    assert asst_msg.role == Role.ASSISTANT
    assert asst_msg.content == "Hello! How can I help?"
    assert asst_msg.metadata.get("model") == "mock-llm"
    assert len(session.messages) == 2


def test_session_get_history_limit() -> None:
    """Verify bounded history retrieval."""
    session = Session()
    for i in range(10):
        session.add_user_message(f"Message {i}")

    assert len(session.get_history()) == 10
    bounded = session.get_history(limit=3)
    assert len(bounded) == 3
    assert bounded[-1].content == "Message 9"


def test_session_clear() -> None:
    """Verify clearing session messages."""
    session = Session()
    session.add_user_message("msg")
    assert len(session.messages) == 1

    session.clear()
    assert len(session.messages) == 0


def test_session_invalid_message_type() -> None:
    """Verify appending non-Message raises SessionError."""
    session = Session()
    with pytest.raises(SessionError, match="Cannot append non-Message object"):
        session.add_message("invalid string"  # type: ignore[arg-type]
                           )


def test_session_manager() -> None:
    """Verify SessionManager create, get, get_or_create, delete operations."""
    mgr = SessionManager()

    s1 = mgr.create_session("sess-1")
    assert s1.session_id == "sess-1"

    # Duplicate create raises SessionError
    with pytest.raises(SessionError, match="already exists"):
        mgr.create_session("sess-1")

    assert mgr.get_session("sess-1") == s1
    assert mgr.get_session("nonexistent") is None

    s2 = mgr.get_or_create_session("sess-2")
    assert s2.session_id == "sess-2"
    assert mgr.get_or_create_session("sess-2") == s2

    assert len(mgr.list_sessions()) == 2
    assert mgr.delete_session("sess-1") is True
    assert mgr.get_session("sess-1") is None
