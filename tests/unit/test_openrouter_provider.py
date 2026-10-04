"""Unit tests for OpenRouter AI provider implementation."""

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
from lyra.providers.openrouter import OpenRouterProvider


@pytest.fixture
def sample_request() -> AIRequest:
    return AIRequest(
        messages=[
            Message(role=Role.USER, content="Hello OpenRouter"),
        ],
        model="meta-llama/llama-3.3-70b-instruct:free",
    )


def test_openrouter_not_configured() -> None:
    """Verify behavior when OpenRouter API key is missing."""
    provider = OpenRouterProvider(api_key=None)
    assert provider.name == "openrouter"
    assert provider.is_configured is False
    assert provider.status == "NOT_CONFIGURED"
    assert asyncio.run(provider.health_check()) is False

    req = AIRequest(messages=[Message(role=Role.USER, content="hi")])
    with pytest.raises(ProviderNotConfiguredError, match="is NOT_CONFIGURED"):
        asyncio.run(provider.generate(req))


def test_openrouter_successful_response(sample_request: AIRequest) -> None:
    """Verify OpenRouter response parsing on success."""
    provider = OpenRouterProvider(api_key="sk-or-v1-testkey")
    assert provider.is_configured is True
    assert provider.status == "READY"
    assert asyncio.run(provider.health_check()) is True

    mock_payload = {
        "id": "gen-123",
        "choices": [
            {
                "message": {
                    "role": "assistant",
                    "content": "Free model response from OpenRouter",
                },
                "finish_reason": "stop",
            }
        ],
        "usage": {
            "prompt_tokens": 15,
            "completion_tokens": 10,
            "total_tokens": 25,
        },
    }

    mock_resp = MagicMock()
    mock_resp.read.return_value = json.dumps(mock_payload).encode("utf-8")
    mock_resp.__enter__.return_value = mock_resp

    with patch("urllib.request.urlopen", return_value=mock_resp):
        response = asyncio.run(provider.generate(sample_request))

    assert response.content == "Free model response from OpenRouter"
    assert response.model == "meta-llama/llama-3.3-70b-instruct:free"
    assert response.role == Role.ASSISTANT
    assert response.finish_reason == "stop"
    assert response.usage is not None
    assert response.usage.prompt_tokens == 15
    assert response.usage.completion_tokens == 10
    assert response.usage.total_tokens == 25


def test_openrouter_authentication_error(sample_request: AIRequest) -> None:
    """Verify 401 error is mapped to ProviderAuthenticationError."""
    provider = OpenRouterProvider(api_key="bad-key")
    http_error = urllib.error.HTTPError(
        url="http://test",
        code=401,
        msg="Unauthorized",
        hdrs={},  # type: ignore[arg-type]
        fp=io.BytesIO(b'{"error": {"message": "Invalid credentials"}}'),
    )

    with patch("urllib.request.urlopen", side_effect=http_error):
        with pytest.raises(ProviderAuthenticationError, match="OpenRouter authentication failed"):
            asyncio.run(provider.generate(sample_request))


def test_openrouter_rate_limit_error(sample_request: AIRequest) -> None:
    """Verify 429 error is mapped to ProviderRateLimitError."""
    provider = OpenRouterProvider(api_key="key")
    http_error = urllib.error.HTTPError(
        url="http://test",
        code=429,
        msg="Too Many Requests",
        hdrs={},  # type: ignore[arg-type]
        fp=io.BytesIO(b'{"error": {"message": "Free tier quota reached"}}'),
    )

    with patch("urllib.request.urlopen", side_effect=http_error):
        with pytest.raises(ProviderRateLimitError, match="OpenRouter rate limit exceeded"):
            asyncio.run(provider.generate(sample_request))


def test_openrouter_timeout_error(sample_request: AIRequest) -> None:
    """Verify network timeout is mapped to ProviderTimeoutError."""
    provider = OpenRouterProvider(api_key="key")

    with patch("urllib.request.urlopen", side_effect=TimeoutError("Request timed out")):
        with pytest.raises(ProviderTimeoutError, match="timed out"):
            asyncio.run(provider.generate(sample_request))


def test_openrouter_malformed_response(sample_request: AIRequest) -> None:
    """Verify response missing choices raises ProviderResponseError."""
    provider = OpenRouterProvider(api_key="key")

    mock_resp = MagicMock()
    mock_resp.read.return_value = b'{"choices": []}'
    mock_resp.__enter__.return_value = mock_resp

    with patch("urllib.request.urlopen", return_value=mock_resp):
        with pytest.raises(ProviderResponseError, match="missing valid choices"):
            asyncio.run(provider.generate(sample_request))
