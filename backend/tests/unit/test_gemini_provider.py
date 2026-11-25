"""Unit tests for Google Gemini AI provider implementation."""

import asyncio
import io
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
from lyra.providers.gemini import GeminiProvider


@pytest.fixture
def sample_request() -> AIRequest:
    return AIRequest(
        messages=[
            Message(role=Role.USER, content="Hello Gemini"),
        ],
        temperature=0.7,
        max_tokens=256,
        system_prompt="You are a helpful assistant.",
    )


def test_gemini_not_configured() -> None:
    """Verify provider behavior when API key is missing."""
    provider = GeminiProvider(api_key=None)
    assert provider.name == "gemini"
    assert provider.is_configured is False
    assert provider.status == "NOT_CONFIGURED"
    assert asyncio.run(provider.health_check()) is False

    req = AIRequest(messages=[Message(role=Role.USER, content="test")])
    with pytest.raises(ProviderNotConfiguredError, match="is NOT_CONFIGURED"):
        asyncio.run(provider.generate(req))


def test_gemini_successful_response(sample_request: AIRequest) -> None:
    """Verify Gemini request building and response translation on success."""
    provider = GeminiProvider(api_key="fake-gemini-key")
    assert provider.is_configured is True
    assert provider.status == "READY"
    assert asyncio.run(provider.health_check()) is True

    mock_body = {
        "candidates": [
            {
                "content": {
                    "parts": [{"text": "Hello from Gemini!"}],
                    "role": "model",
                },
                "finishReason": "STOP",
            }
        ],
        "usageMetadata": {
            "promptTokenCount": 10,
            "candidatesTokenCount": 15,
            "totalTokenCount": 25,
        },
    }

    mock_resp = MagicMock()
    mock_resp.read.return_value = json_bytes(mock_body)
    mock_resp.__enter__.return_value = mock_resp

    with patch("urllib.request.urlopen", return_value=mock_resp):
        response = asyncio.run(provider.generate(sample_request))

    assert response.content == "Hello from Gemini!"
    assert response.model == "gemini-2.5-flash"
    assert response.role == Role.ASSISTANT
    assert response.finish_reason == "STOP"
    assert response.usage is not None
    assert response.usage.prompt_tokens == 10
    assert response.usage.completion_tokens == 15
    assert response.usage.total_tokens == 25


def test_gemini_authentication_error(sample_request: AIRequest) -> None:
    """Verify 401/403 HTTP errors are mapped to ProviderAuthenticationError."""
    provider = GeminiProvider(api_key="invalid-key")
    http_error = urllib.error.HTTPError(
        url="http://test",
        code=401,
        msg="Unauthorized",
        hdrs={},  # type: ignore[arg-type]
        fp=io.BytesIO(b'{"error": {"message": "API key not valid"}}'),
    )

    with patch("urllib.request.urlopen", side_effect=http_error):
        with pytest.raises(ProviderAuthenticationError, match="authentication failed"):
            asyncio.run(provider.generate(sample_request))


def test_gemini_rate_limit_error(sample_request: AIRequest) -> None:
    """Verify 429 HTTP error is mapped to ProviderRateLimitError."""
    provider = GeminiProvider(api_key="fake-key")
    http_error = urllib.error.HTTPError(
        url="http://test",
        code=429,
        msg="Too Many Requests",
        hdrs={},  # type: ignore[arg-type]
        fp=io.BytesIO(b'{"error": {"message": "Resource has been exhausted"}}'),
    )

    with patch("urllib.request.urlopen", side_effect=http_error):
        with pytest.raises(ProviderRateLimitError, match="rate limit exceeded"):
            asyncio.run(provider.generate(sample_request))


def test_gemini_timeout_error(sample_request: AIRequest) -> None:
    """Verify network timeouts are mapped to ProviderTimeoutError."""
    provider = GeminiProvider(api_key="fake-key")

    with patch("urllib.request.urlopen", side_effect=TimeoutError("Request timed out")):
        with pytest.raises(ProviderTimeoutError, match="timed out"):
            asyncio.run(provider.generate(sample_request))


def test_gemini_malformed_response(sample_request: AIRequest) -> None:
    """Verify malformed JSON or unexpected schemas raise ProviderResponseError."""
    provider = GeminiProvider(api_key="fake-key")

    mock_resp = MagicMock()
    mock_resp.read.return_value = b'{"candidates": []}'  # Missing candidates
    mock_resp.__enter__.return_value = mock_resp

    with patch("urllib.request.urlopen", return_value=mock_resp):
        with pytest.raises(ProviderResponseError, match="missing valid candidates"):
            asyncio.run(provider.generate(sample_request))


def json_bytes(obj: dict) -> bytes:
    import json
    return json.dumps(obj).encode("utf-8")


def test_gemini_streaming_tokens(sample_request: AIRequest) -> None:
    """Verify Gemini provider streams tokens via SSE line parsing."""
    provider = GeminiProvider(api_key="test-streaming-key")
    assert provider.supports_streaming is True

    sse_payload = (
        b'data: {"candidates": [{"content": {"parts": [{"text": "Hello "}]}}]}\n\n'
        b'data: {"candidates": [{"content": {"parts": [{"text": "world!"}]}}]}\n\n'
    )
    mock_resp = MagicMock()
    mock_resp.__iter__.return_value = sse_payload.splitlines(keepends=True)
    mock_resp.__enter__.return_value = mock_resp

    with patch("urllib.request.urlopen", return_value=mock_resp):
        async def _collect():
            return [t async for t in provider.stream(sample_request)]

        tokens = asyncio.run(_collect())

    assert tokens == ["Hello ", "world!"]


def test_router_selects_gemini_when_configured(sample_request: AIRequest) -> None:
    """Verify that when GEMINI_API_KEY is configured, the router selects Gemini first."""
    from lyra.config.settings import Settings
    from lyra.providers.local import LocalProvider, LocalProviderConfig
    from lyra.routing.health import ProviderHealthTracker
    from lyra.routing.router import ModelRouter
    from lyra.routing.strategies import PriorityFallbackStrategy

    gemini = GeminiProvider(api_key="valid-gemini-key")
    local = LocalProvider(config=LocalProviderConfig.from_settings(Settings(local_provider_enabled=False)))

    assert gemini.is_configured is True
    assert local.is_configured is False

    strategy = PriorityFallbackStrategy(["gemini", "local"])
    tracker = ProviderHealthTracker()
    candidates = strategy.select_candidates([gemini, local], sample_request, tracker)

    assert len(candidates) == 1
    assert candidates[0].name == "gemini"


def test_local_provider_not_required_when_unconfigured() -> None:
    """Verify LocalProvider is not configured by default and LYRA runs without Ollama."""
    from lyra.config.settings import Settings
    from lyra.providers.local import LocalProvider, LocalProviderConfig

    settings = Settings(local_provider_enabled=False)
    local = LocalProvider(config=LocalProviderConfig.from_settings(settings))
    assert local.is_configured is False


def test_graceful_behavior_when_gemini_key_missing() -> None:
    """Verify that when GEMINI_API_KEY is missing, LYRA returns a graceful unconfigured notice without calling Ollama."""
    from lyra.companion.orchestrator import CompanionOrchestrator, UNCONFIGURED_ASSISTANCE_MESSAGE
    from lyra.companion.session import Session
    from lyra.config.settings import Settings
    from lyra.providers.local import LocalProvider, LocalProviderConfig
    from lyra.routing.router import ModelRouter
    from lyra.routing.strategies import PriorityFallbackStrategy
    from lyra.tools.registry import ToolRegistry

    gemini = GeminiProvider(api_key="")
    local = LocalProvider(config=LocalProviderConfig.from_settings(Settings(local_provider_enabled=False)))
    router = ModelRouter(providers=[gemini, local], strategy=PriorityFallbackStrategy(["gemini", "local"]))
    orchestrator = CompanionOrchestrator(router=router, tool_registry=ToolRegistry())

    session = Session()
    reply = asyncio.run(orchestrator.process_turn(session, "Hello LYRA"))
    assert reply == UNCONFIGURED_ASSISTANCE_MESSAGE

