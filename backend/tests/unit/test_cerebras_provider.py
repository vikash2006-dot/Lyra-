"""Unit tests for Cerebras Cloud AI provider implementation."""

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
from lyra.providers.cerebras import CerebrasProvider


@pytest.fixture
def sample_request() -> AIRequest:
    return AIRequest(
        messages=[
            Message(role=Role.USER, content="Hello Cerebras"),
        ],
        model="llama-3.3-70b",
        temperature=0.2,
    )


def test_cerebras_not_configured() -> None:
    """Verify behavior when Cerebras API key is missing."""
    provider = CerebrasProvider(api_key=None)
    assert provider.name == "cerebras"
    assert provider.is_configured is False
    assert provider.status == "NOT_CONFIGURED"
    assert asyncio.run(provider.health_check()) is False

    req = AIRequest(messages=[Message(role=Role.USER, content="hi")])
    with pytest.raises(ProviderNotConfiguredError, match="is NOT_CONFIGURED"):
        asyncio.run(provider.generate(req))


def test_cerebras_successful_response(sample_request: AIRequest) -> None:
    """Verify Cerebras response parsing on success."""
    provider = CerebrasProvider(api_key="csk-testkey")
    assert provider.is_configured is True
    assert provider.status == "READY"
    assert asyncio.run(provider.health_check()) is True

    mock_payload = {
        "id": "chatcmpl-cerebras-123",
        "choices": [
            {
                "message": {
                    "role": "assistant",
                    "content": "Ultra-fast response from Cerebras!",
                },
                "finish_reason": "stop",
            }
        ],
        "usage": {
            "prompt_tokens": 8,
            "completion_tokens": 12,
            "total_tokens": 20,
        },
    }

    mock_resp = MagicMock()
    mock_resp.read.return_value = json.dumps(mock_payload).encode("utf-8")
    mock_resp.__enter__.return_value = mock_resp

    with patch("urllib.request.urlopen", return_value=mock_resp):
        response = asyncio.run(provider.generate(sample_request))

    assert response.content == "Ultra-fast response from Cerebras!"
    assert response.model == "llama-3.3-70b"
    assert response.role == Role.ASSISTANT
    assert response.finish_reason == "stop"
    assert response.usage is not None
    assert response.usage.prompt_tokens == 8
    assert response.usage.completion_tokens == 12
    assert response.usage.total_tokens == 20


def test_cerebras_authentication_error(sample_request: AIRequest) -> None:
    """Verify 401 error is mapped to ProviderAuthenticationError."""
    provider = CerebrasProvider(api_key="bad-key")
    http_error = urllib.error.HTTPError(
        url="http://test",
        code=401,
        msg="Unauthorized",
        hdrs={},  # type: ignore[arg-type]
        fp=io.BytesIO(b'{"error": {"message": "Invalid Bearer token"}}'),
    )

    with patch("urllib.request.urlopen", side_effect=http_error):
        with pytest.raises(ProviderAuthenticationError, match="Cerebras authentication failed"):
            asyncio.run(provider.generate(sample_request))


def test_cerebras_rate_limit_error(sample_request: AIRequest) -> None:
    """Verify 429 error is mapped to ProviderRateLimitError."""
    provider = CerebrasProvider(api_key="key")
    http_error = urllib.error.HTTPError(
        url="http://test",
        code=429,
        msg="Too Many Requests",
        hdrs={},  # type: ignore[arg-type]
        fp=io.BytesIO(b'{"error": {"message": "Tokens per minute limit reached"}}'),
    )

    with patch("urllib.request.urlopen", side_effect=http_error):
        with pytest.raises(ProviderRateLimitError, match="Cerebras rate limit exceeded"):
            asyncio.run(provider.generate(sample_request))


def test_cerebras_timeout_error(sample_request: AIRequest) -> None:
    """Verify network timeout is mapped to ProviderTimeoutError."""
    provider = CerebrasProvider(api_key="key")

    with patch("urllib.request.urlopen", side_effect=TimeoutError("Request timed out")):
        with pytest.raises(ProviderTimeoutError, match="timed out"):
            asyncio.run(provider.generate(sample_request))


def test_cerebras_malformed_response(sample_request: AIRequest) -> None:
    """Verify invalid JSON raises ProviderResponseError."""
    provider = CerebrasProvider(api_key="key")

    mock_resp = MagicMock()
    mock_resp.read.return_value = b"<html>Service Unavailable</html>"
    mock_resp.__enter__.return_value = mock_resp

    with patch("urllib.request.urlopen", return_value=mock_resp):
        with pytest.raises(ProviderResponseError, match="returned invalid JSON"):
            asyncio.run(provider.generate(sample_request))
