"""Unit tests for LYRA conversational context preparation."""

import pytest

from lyra.companion.context import ConversationContext
from lyra.companion.personality import PersonalityProfile
from lyra.companion.session import Session
from lyra.models.messages import Message, Role


def test_build_request_from_string() -> None:
    """Verify building AIRequest from a string user prompt."""
    profile = PersonalityProfile(name="LYRA-Test")
    ctx = ConversationContext(personality=profile)
    session = Session(session_id="test-sess")

    request = ctx.build_request(session, "What is the capital of France?")

    assert request.system_prompt is not None
    assert "You are LYRA-Test" in request.system_prompt
    assert len(request.messages) == 1
    assert request.messages[0].role == Role.USER
    assert request.messages[0].content == "What is the capital of France?"
    assert request.metadata.get("session_id") == "test-sess"


def test_build_request_preserves_conversation_history() -> None:
    """Verify that previous turns in session history are included in chronological order."""
    ctx = ConversationContext()
    session = Session()

    session.add_user_message("My name is Alice.")
    session.add_assistant_message("Nice to meet you, Alice!")

    request = ctx.build_request(session, "What is my name?")

    assert len(request.messages) == 3
    assert request.messages[0].content == "My name is Alice."
    assert request.messages[1].content == "Nice to meet you, Alice!"
    assert request.messages[2].content == "What is my name?"


def test_build_request_invalid_type() -> None:
    """Verify non-str and non-Message raises ValueError."""
    ctx = ConversationContext()
    session = Session()

    with pytest.raises(ValueError, match="user_message must be a str or Message"):
        ctx.build_request(session, 12345  # type: ignore[arg-type]
                          )
