"""Unit tests for LYRA internal message, request, and response models."""

import pytest

from lyra.core.exceptions import ModelValidationError
from lyra.models.messages import (
    AIRequest,
    AIResponse,
    Message,
    Role,
    Usage,
)


def test_message_valid_creation() -> None:
    """Verify that Message creates successfully with valid Role and content."""
    msg = Message(role=Role.USER, content="Hello LYRA")
    assert msg.role == Role.USER
    assert msg.content == "Hello LYRA"
    assert msg.name is None
    assert msg.metadata == {}


def test_message_role_string_coercion() -> None:
    """Verify that string roles are coerced into Role enums."""
    msg = Message(role="system", content="You are LYRA.")  # type: ignore[arg-type]
    assert msg.role == Role.SYSTEM


def test_message_invalid_role() -> None:
    """Verify that invalid role strings or types raise ModelValidationError."""
    with pytest.raises(ModelValidationError, match="Invalid message role"):
        Message(role="invalid_role", content="hi")  # type: ignore[arg-type]

    with pytest.raises(ModelValidationError, match="Invalid message role type"):
        Message(role=123, content="hi")  # type: ignore[arg-type]


def test_message_invalid_content_type() -> None:
    """Verify that non-string content raises ModelValidationError."""
    with pytest.raises(ModelValidationError, match="Message content must be a string"):
        Message(role=Role.USER, content=None)  # type: ignore[arg-type]


def test_usage_valid_and_total_calculation() -> None:
    """Verify Usage token calculation and immutability."""
    usage = Usage(prompt_tokens=10, completion_tokens=25)
    assert usage.total_tokens == 35

    explicit_usage = Usage(prompt_tokens=10, completion_tokens=25, total_tokens=40)
    assert explicit_usage.total_tokens == 40


def test_usage_negative_tokens() -> None:
    """Verify that negative token numbers raise ModelValidationError."""
    with pytest.raises(ModelValidationError, match="Token counts must be non-negative"):
        Usage(prompt_tokens=-1)


def test_airequest_valid_creation() -> None:
    """Verify valid AIRequest initialization."""
    msg = Message(role=Role.USER, content="Summarize this")
    req = AIRequest(
        messages=[msg],
        model="test-model",
        temperature=0.7,
        max_tokens=500,
        system_prompt="Be concise",
        metadata={"user_id": "test-user"},
    )

    assert len(req.messages) == 1
    assert req.messages[0] == msg
    assert req.model == "test-model"
    assert req.temperature == 0.7
    assert req.max_tokens == 500
    assert req.system_prompt == "Be concise"
    assert req.metadata == {"user_id": "test-user"}


def test_airequest_empty_messages() -> None:
    """Verify that an AIRequest with no messages raises ModelValidationError."""
    with pytest.raises(ModelValidationError, match="requires at least one Message"):
        AIRequest(messages=[])


def test_airequest_invalid_message_item() -> None:
    """Verify that non-Message items in messages raise ModelValidationError."""
    with pytest.raises(ModelValidationError, match="is not a Message instance"):
        AIRequest(messages=["not a message object"])  # type: ignore[arg-type]


def test_airequest_invalid_temperature() -> None:
    """Verify that out-of-bounds or non-numeric temperatures raise ModelValidationError."""
    msg = Message(role=Role.USER, content="Hello")

    with pytest.raises(ModelValidationError, match="Temperature must be a float between 0.0 and 2.0"):
        AIRequest(messages=[msg], temperature=-0.1)

    with pytest.raises(ModelValidationError, match="Temperature must be a float between 0.0 and 2.0"):
        AIRequest(messages=[msg], temperature=2.5)


def test_airequest_invalid_max_tokens() -> None:
    """Verify that non-positive max_tokens raise ModelValidationError."""
    msg = Message(role=Role.USER, content="Hello")

    with pytest.raises(ModelValidationError, match="max_tokens must be a positive integer"):
        AIRequest(messages=[msg], max_tokens=0)

    with pytest.raises(ModelValidationError, match="max_tokens must be a positive integer"):
        AIRequest(messages=[msg], max_tokens=-50)


def test_airesponse_valid_creation() -> None:
    """Verify valid AIResponse creation."""
    resp = AIResponse(
        content="Response from LYRA",
        model="test-llm",
        role=Role.ASSISTANT,
        finish_reason="stop",
        usage=Usage(prompt_tokens=5, completion_tokens=10),
    )

    assert resp.content == "Response from LYRA"
    assert resp.model == "test-llm"
    assert resp.role == Role.ASSISTANT
    assert resp.finish_reason == "stop"
    assert resp.usage is not None
    assert resp.usage.total_tokens == 15


def test_airesponse_invalid_model() -> None:
    """Verify that empty or missing model identifier raises ModelValidationError."""
    with pytest.raises(ModelValidationError, match="requires a valid non-empty model identifier"):
        AIResponse(content="test", model="")


def test_airesponse_invalid_content() -> None:
    """Verify that non-string content raises ModelValidationError."""
    with pytest.raises(ModelValidationError, match="AIResponse content must be a string"):
        AIResponse(content=None, model="test-model")  # type: ignore[arg-type]
