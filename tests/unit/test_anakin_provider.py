"""Unit tests for Anakin AI provider implementation."""

import asyncio
import io
import json
from unittest.mock import MagicMock, patch
import urllib.error
import pytest

from lyra.core.exceptions import (
    ProviderAuthenticationError,
    ProviderNotConfiguredError,
    ProviderQuotaExceededError,
    ProviderRateLimitError,
    ProviderResponseError,
    ProviderTimeoutError,
)
from lyra.models.messages import AIRequest, Message, Role
from lyra.providers.anakin import AnakinClient, AnakinProvider


@pytest.fixture
def sample_request() -> AIRequest:
    return AIRequest(
        messages=[
            Message(role=Role.SYSTEM, content="System prompt"),
            Message(role=Role.USER, content="Hello Anakin"),
        ],
        temperature=0.7,
        max_tokens=150,
    )


def test_anakin_not_configured() -> None:
    """Verify behavior when Anakin API key is missing."""
    provider = AnakinProvider(api_key=None)
    assert provider.name == "anakin"
    assert provider.is_configured is False
    assert provider.status == "NOT_CONFIGURED"
    assert asyncio.run(provider.health_check()) is False

    req = AIRequest(messages=[Message(role=Role.USER, content="hi")])
    with pytest.raises(ProviderNotConfiguredError, match="is NOT_CONFIGURED"):
        asyncio.run(provider.generate(req))


def test_anakin_successful_quickapp_response(sample_request: AIRequest) -> None:
    """Verify Anakin Quick App execution and response parsing."""
    provider = AnakinProvider(
        api_key="ask_test_key_123",
        app_id="quickapp_test_app",
        app_type="quickapp",
    )
    assert provider.is_configured is True
    assert provider.status == "READY"
    assert asyncio.run(provider.health_check()) is True

    mock_payload = {
        "id": "run_12345",
        "status": "COMPLETED",
        "result": "Hello from Anakin Quick App!",
    }

    mock_resp = MagicMock()
    mock_resp.read.return_value = json.dumps(mock_payload).encode("utf-8")
    mock_resp.__enter__.return_value = mock_resp

    with patch("urllib.request.urlopen", return_value=mock_resp):
        response = asyncio.run(provider.generate(sample_request))

    assert response.content == "Hello from Anakin Quick App!"
    assert response.model == "anakin-quickapp_test_app"
    assert response.role == Role.ASSISTANT
    assert response.finish_reason == "stop"
    assert response.metadata["provider"] == "anakin"


def test_anakin_successful_chatbot_response(sample_request: AIRequest) -> None:
    """Verify Anakin Chatbot message execution."""
    provider = AnakinProvider(
        api_key="ask_test_key_123",
        app_id="chatbot_test_app",
        app_type="chatbot",
    )
    mock_payload = {
        "id": "msg_9876",
        "conversation_id": "conv_456",
        "content": "Hello from Anakin Chatbot!",
    }

    mock_resp = MagicMock()
    mock_resp.read.return_value = json.dumps(mock_payload).encode("utf-8")
    mock_resp.__enter__.return_value = mock_resp

    with patch("urllib.request.urlopen", return_value=mock_resp):
        response = asyncio.run(provider.generate(sample_request))

    assert response.content == "Hello from Anakin Chatbot!"
    assert response.model == "anakin-chatbot_test_app"
    assert response.role == Role.ASSISTANT


def test_anakin_authentication_error(sample_request: AIRequest) -> None:
    """Verify 401 error is mapped to ProviderAuthenticationError."""
    provider = AnakinProvider(api_key="bad_key", app_id="test_app")
    http_error = urllib.error.HTTPError(
        url="http://test",
        code=401,
        msg="Unauthorized",
        hdrs={},  # type: ignore[arg-type]
        fp=io.BytesIO(b'{"error": {"message": "Invalid API Key"}}'),
    )

    with patch("urllib.request.urlopen", side_effect=http_error):
        with pytest.raises(ProviderAuthenticationError, match="Anakin authentication failed"):
            asyncio.run(provider.generate(sample_request))


def test_anakin_rate_limit_error(sample_request: AIRequest) -> None:
    """Verify 429 error is mapped to ProviderRateLimitError."""
    provider = AnakinProvider(api_key="ask_key", app_id="test_app")
    http_error = urllib.error.HTTPError(
        url="http://test",
        code=429,
        msg="Too Many Requests",
        hdrs={},  # type: ignore[arg-type]
        fp=io.BytesIO(b'{"error": "Too Many Requests"}'),
    )

    with patch("urllib.request.urlopen", side_effect=http_error):
        with pytest.raises(ProviderRateLimitError, match="Anakin rate limit exceeded"):
            asyncio.run(provider.generate(sample_request))


def test_anakin_quota_error(sample_request: AIRequest) -> None:
    """Verify 429 with quota notice is mapped to ProviderQuotaExceededError."""
    provider = AnakinProvider(api_key="ask_key", app_id="test_app")
    http_error = urllib.error.HTTPError(
        url="http://test",
        code=429,
        msg="Quota Exceeded",
        hdrs={},  # type: ignore[arg-type]
        fp=io.BytesIO(b'{"error": "User credits or quota exhausted"}'),
    )

    with patch("urllib.request.urlopen", side_effect=http_error):
        with pytest.raises(ProviderQuotaExceededError, match="Anakin quota/credits exhausted"):
            asyncio.run(provider.generate(sample_request))


def test_anakin_timeout_error(sample_request: AIRequest) -> None:
    """Verify network timeout is mapped to ProviderTimeoutError."""
    provider = AnakinProvider(api_key="ask_key", app_id="test_app")

    with patch("urllib.request.urlopen", side_effect=TimeoutError("Connection timed out")):
        with pytest.raises(ProviderTimeoutError, match="timed out"):
            asyncio.run(provider.generate(sample_request))


def test_anakin_malformed_response(sample_request: AIRequest) -> None:
    """Verify non-JSON response raises ProviderResponseError."""
    provider = AnakinProvider(api_key="ask_key", app_id="test_app")

    mock_resp = MagicMock()
    mock_resp.read.return_value = b"<html>Bad Gateway</html>"
    mock_resp.__enter__.return_value = mock_resp

    with patch("urllib.request.urlopen", return_value=mock_resp):
        with pytest.raises(ProviderResponseError, match="invalid JSON response"):
            asyncio.run(provider.generate(sample_request))


def test_anakin_bounded_retry_on_502(sample_request: AIRequest) -> None:
    """Verify bounded retry with exponential backoff on transient 502/503 errors."""
    provider = AnakinProvider(api_key="ask_key", app_id="test_app")

    http_error_502 = urllib.error.HTTPError(
        url="http://test",
        code=502,
        msg="Bad Gateway",
        hdrs={},  # type: ignore[arg-type]
        fp=io.BytesIO(b"Bad Gateway"),
    )

    mock_success = MagicMock()
    mock_success.read.return_value = json.dumps({"result": "Recovered after 502"}).encode("utf-8")
    mock_success.__enter__.return_value = mock_success

    # First attempt raises 502, second attempt succeeds
    with patch("urllib.request.urlopen", side_effect=[http_error_502, mock_success]), patch("time.sleep"):
        response = asyncio.run(provider.generate(sample_request))

    assert response.content == "Recovered after 502"


def test_anakin_streaming(sample_request: AIRequest) -> None:
    """Verify token streaming via SSE parsing."""
    provider = AnakinProvider(api_key="ask_key", app_id="test_app")

    sse_lines = [
        b'data: {"text": "Hello "}\n',
        b'data: {"text": "world!"}\n',
        b"data: [DONE]\n",
    ]

    mock_resp = MagicMock()
    mock_resp.__iter__.return_value = iter(sse_lines)
    mock_resp.__enter__.return_value = mock_resp

    with patch("urllib.request.urlopen", return_value=mock_resp):
        tokens = []

        async def _consume():
            async for token in provider.stream(sample_request):
                tokens.append(token)

        asyncio.run(_consume())

    assert tokens == ["Hello ", "world!"]
