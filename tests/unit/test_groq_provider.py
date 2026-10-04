"""Unit tests for Groq Cloud AI provider implementation."""

import asyncio
import io
import json
from unittest.mock import MagicMock, patch
import urllib.error
import pytest

from lyra.core.exceptions import (
    ProviderAuthenticationError,
    ProviderNotConfiguredError,
    ProviderRateLimitError,
    ProviderResponseError,
    ProviderTimeoutError,
)
from lyra.models.messages import AIRequest, Message, Role
from lyra.providers.groq import GroqProvider


@pytest.fixture
def sample_request() -> AIRequest:
    return AIRequest(
        messages=[
            Message(role=Role.SYSTEM, content="System prompt"),
            Message(role=Role.USER, content="Hello Groq"),
        ],
        temperature=0.5,
        max_tokens=100,
    )


def test_groq_not_configured() -> None:
    """Verify behavior when Groq API key is missing."""
    provider = GroqProvider(api_key=None)
    assert provider.name == "groq"
    assert provider.is_configured is False
    assert provider.status == "NOT_CONFIGURED"
    assert asyncio.run(provider.health_check()) is False

    req = AIRequest(messages=[Message(role=Role.USER, content="hi")])
    with pytest.raises(ProviderNotConfiguredError, match="is NOT_CONFIGURED"):
        asyncio.run(provider.generate(req))


def test_groq_successful_response(sample_request: AIRequest) -> None:
    """Verify Groq response parsing and canonical AIResponse generation."""
    provider = GroqProvider(api_key="gsk-testkey")
    assert provider.is_configured is True
    assert provider.status == "READY"
    assert asyncio.run(provider.health_check()) is True

    mock_payload = {
        "id": "chatcmpl-123",
        "choices": [
            {
                "message": {
                    "role": "assistant",
                    "content": "Hello! I am Groq running LLaMA.",
                },
                "finish_reason": "stop",
            }
        ],
        "usage": {
            "prompt_tokens": 12,
            "completion_tokens": 8,
            "total_tokens": 20,
        },
    }

    mock_resp = MagicMock()
    mock_resp.read.return_value = json.dumps(mock_payload).encode("utf-8")
    mock_resp.__enter__.return_value = mock_resp

    with patch("urllib.request.urlopen", return_value=mock_resp):
        response = asyncio.run(provider.generate(sample_request))

    assert response.content == "Hello! I am Groq running LLaMA."
    assert response.model == "llama-3.3-70b-versatile"
    assert response.role == Role.ASSISTANT
    assert response.finish_reason == "stop"
    assert response.usage is not None
    assert response.usage.prompt_tokens == 12
    assert response.usage.completion_tokens == 8
    assert response.usage.total_tokens == 20


def test_groq_authentication_error(sample_request: AIRequest) -> None:
    """Verify 401 error is mapped to ProviderAuthenticationError."""
    provider = GroqProvider(api_key="bad-key")
    http_error = urllib.error.HTTPError(
        url="http://test",
        code=401,
        msg="Unauthorized",
        hdrs={},  # type: ignore[arg-type]
        fp=io.BytesIO(b'{"error": {"message": "Invalid API Key"}}'),
    )

    with patch("urllib.request.urlopen", side_effect=http_error):
        with pytest.raises(ProviderAuthenticationError, match="Groq authentication failed"):
            asyncio.run(provider.generate(sample_request))


def test_groq_rate_limit_error(sample_request: AIRequest) -> None:
    """Verify 429 error is mapped to ProviderRateLimitError."""
    provider = GroqProvider(api_key="key")
    http_error = urllib.error.HTTPError(
        url="http://test",
        code=429,
        msg="Too Many Requests",
        hdrs={},  # type: ignore[arg-type]
        fp=io.BytesIO(b'{"error": {"message": "Rate limit reached"}}'),
    )

    with patch("urllib.request.urlopen", side_effect=http_error):
        with pytest.raises(ProviderRateLimitError, match="Groq rate limit exceeded"):
            asyncio.run(provider.generate(sample_request))


def test_groq_timeout_error(sample_request: AIRequest) -> None:
    """Verify network timeout is mapped to ProviderTimeoutError."""
    provider = GroqProvider(api_key="key")

    with patch("urllib.request.urlopen", side_effect=TimeoutError("Connection timed out")):
        with pytest.raises(ProviderTimeoutError, match="timed out"):
            asyncio.run(provider.generate(sample_request))


def test_groq_malformed_response(sample_request: AIRequest) -> None:
    """Verify response missing content raises ProviderResponseError."""
    provider = GroqProvider(api_key="key")

    mock_resp = MagicMock()
    mock_resp.read.return_value = b'{"choices": [{"message": {}}]}'
    mock_resp.__enter__.return_value = mock_resp

    with patch("urllib.request.urlopen", return_value=mock_resp):
        with pytest.raises(ProviderResponseError, match="missing text content"):
            asyncio.run(provider.generate(sample_request))
