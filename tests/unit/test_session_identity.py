"""Unit tests for Session Identity and Authentication Integration."""

import time
import pytest

from lyra.companion.session import Session, SessionManager
from lyra.models.identity import AuthenticationState, User


def test_session_default_anonymous_state():
    """Verify default session has anonymous authentication state."""
    session = Session()
    assert session.user_id == "default_user"
    assert session.auth_state == AuthenticationState.ANONYMOUS
    assert session.is_authenticated is False
    assert session.auth_token is None
    assert session.last_activity == session.created_at


def test_session_bind_user():
    """Verify binding User identity updates user_id, auth_state, token, and metadata."""
    session = Session()
    user = User(
        id="user-999",
        username="clara",
        display_name="Clara Oswald",
        metadata={"timezone": "UTC"},
    )

    session.bind_user(user, auth_token="tok_12345")

    assert session.user_id == "user-999"
    assert session.auth_state == AuthenticationState.AUTHENTICATED
    assert session.is_authenticated is True
    assert session.auth_token == "tok_12345"
    assert session.metadata["username"] == "clara"
    assert session.metadata["display_name"] == "Clara Oswald"


def test_session_last_activity_and_expiration():
    """Verify last_activity updates on message addition and is_expired calculation."""
    session = Session()
    initial_time = session.last_activity

    time.sleep(0.01)
    session.add_user_message("Hello LYRA")

    assert session.last_activity > initial_time

    # Expiration test with explicit idle time
    assert session.is_expired(max_idle_seconds=100.0) is False

    # Simulate past activity
    session.last_activity = time.time() - 20.0
    assert session.is_expired(max_idle_seconds=10.0) is True


def test_session_logout():
    """Verify session logout clears auth_state and token while retaining message history."""
    session = Session()
    user = User(id="u-1", username="doctor", display_name="The Doctor")
    session.bind_user(user, auth_token="token_abc")
    session.add_user_message("Tardis coordinates")

    assert session.is_authenticated is True

    session.logout()

    assert session.auth_state == AuthenticationState.ANONYMOUS
    assert session.is_authenticated is False
    assert session.auth_token is None
    assert "username" not in session.metadata
    assert len(session.messages) == 1


def test_session_manager_with_auth_state():
    """Verify SessionManager supports auth state on session creation."""
    mgr = SessionManager()
    user = User(id="u-77", username="amy_pond", display_name="Amy Pond")

    session = mgr.create_session(
        session_id="sess-77",
        user_id=user.id,
        auth_state=AuthenticationState.AUTHENTICATED,
        auth_token="sample_tok",
    )

    assert session.session_id == "sess-77"
    assert session.user_id == "u-77"
    assert session.is_authenticated is True
    assert session.auth_token == "sample_tok"
