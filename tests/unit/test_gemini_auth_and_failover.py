"""Unit tests specifically verifying Gemini API-Key authentication, 401 handling,
streaming, error classification, auto-failover, cooldown, and recovery in LYRA.

Covers:
1. Gemini API-key authentication (verifies x-goog-api-key header in generate & stream)
2. Missing GEMINI_API_KEY
3. Invalid Gemini key
4. Gemini 401 authentication error
5. Gemini 429 quota error
6. Gemini streaming success
7. Gemini streaming 401
8. Gemini streaming 429
9. Provider fallback after 401
10. Provider fallback after 429
11. Ollama unavailable
12. Grok fallback
13. Groq fallback
14. Cerebras fallback
15. OpenRouter fallback
16. All providers unavailable
17. Provider recovery
18. Tool calling after fallback
19. Voice loop after fallback
"""

import asyncio
import io
import json
import time
from unittest.mock import AsyncMock, MagicMock, patch
import urllib.error
import pytest

from lyra.companion.orchestrator import CompanionOrchestrator
from lyra.companion.session import Session
from lyra.config.settings import Settings
from lyra.core.exceptions import (
    NoAvailableProviderError,
    ProviderAuthenticationError,
    ProviderError,
    ProviderNotConfiguredError,
    ProviderQuotaExceededError,
    ProviderRateLimitError,
)
from lyra.models.messages import AIRequest, AIResponse, Message, Role
from lyra.models.stream import StreamCompleted, StreamError, StreamStarted, TextDelta
from lyra.models.tools import ToolResult
from lyra.providers.base import AIProvider
from lyra.providers.gemini import GeminiProvider
from lyra.providers.local import LocalProvider, LocalProviderConfig
from lyra.routing.health import (
    FailureCategory,
    ProviderHealthStatus,
    ProviderHealthTracker,
    classify_failure,
)
from lyra.routing.router import ModelRouter
from lyra.routing.strategies import PriorityFallbackStrategy
from lyra.tools.executor import ToolExecutor
from lyra.tools.registry import ToolRegistry


class MockCandidate(AIProvider):
    def __init__(
        self,
        name: str,
        configured: bool = True,
        response_text: str = "Mock response",
        fail_with: Exception | None = None,
        stream_tokens: list[str] | None = None,
    ) -> None:
        self._name = name
        self._configured = configured
        self.response_text = response_text
        self.fail_with = fail_with
        self.stream_tokens = stream_tokens or ["Token1", "Token2"]
        self.calls = 0

    @property
    def name(self) -> str:
        return self._name

    @property
    def is_configured(self) -> bool:
        return self._configured

    @property
    def supports_streaming(self) -> bool:
        return True

    async def generate(self, request: AIRequest) -> AIResponse:
        self.calls += 1
        if self.fail_with:
            raise self.fail_with
        return AIResponse(content=self.response_text, model=f"{self._name}-m", role=Role.ASSISTANT)

    async def stream(self, request: AIRequest):
        self.calls += 1
        if self.fail_with:
            raise self.fail_with
        for t in self.stream_tokens:
            yield t


@pytest.fixture
def req() -> AIRequest:
    return AIRequest(messages=[Message(role=Role.USER, content="Hello")])


# 1. Gemini API-Key Authentication Header
def test_1_gemini_api_key_header_sent_in_generate(req):
    """Verify GeminiProvider attaches x-goog-api-key header on REST generateContent request."""
    provider = GeminiProvider(api_key="AQ.TestSecretKey123")
    captured_req = None

    def _mock_urlopen(r, timeout=None):
        nonlocal captured_req
        captured_req = r
        resp = MagicMock()
        resp.read.return_value = json.dumps({
            "candidates": [{"content": {"parts": [{"text": "Gemini answer"}]}}]
        }).encode()
        resp.__enter__.return_value = resp
        return resp

    with patch("urllib.request.urlopen", side_effect=_mock_urlopen):
        resp = asyncio.run(provider.generate(req))

    assert resp.content == "Gemini answer"
    assert captured_req is not None
    # Verify x-goog-api-key header is present and populated
    assert captured_req.headers.get("X-goog-api-key") == "AQ.TestSecretKey123"
    # Ensure no OAuth Bearer header is sent
    assert "Authorization" not in captured_req.headers


# 2. Missing GEMINI_API_KEY
def test_2_missing_gemini_api_key(req):
    """Verify missing GEMINI_API_KEY marks provider as not configured and raises ProviderNotConfiguredError."""
    provider = GeminiProvider(api_key="")
    assert provider.is_configured is False
    with pytest.raises(ProviderNotConfiguredError):
        asyncio.run(provider.generate(req))


# 3. Invalid Gemini Key
def test_3_invalid_gemini_key_401(req):
    """Verify invalid API key returning 401 raises ProviderAuthenticationError with normalized message."""
    provider = GeminiProvider(api_key="AQ.InvalidKey")
    err_body = json.dumps({
        "error": {
            "code": 401,
            "message": "Request had invalid authentication credentials.",
            "status": "UNAUTHENTICATED",
            "details": [{"reason": "ACCESS_TOKEN_TYPE_UNSUPPORTED"}],
        }
    }).encode()
    http_error = urllib.error.HTTPError(
        url="https://generativelanguage.googleapis.com",
        code=401,
        msg="UNAUTHENTICATED",
        hdrs={},
        fp=io.BytesIO(err_body),
    )

    with patch("urllib.request.urlopen", side_effect=http_error):
        with pytest.raises(ProviderAuthenticationError) as exc_info:
            asyncio.run(provider.generate(req))
        assert "401" in str(exc_info.value)
        assert classify_failure(exc_info.value) == FailureCategory.AUTHENTICATION_ERROR


# 4. Gemini 401 Classification & Router Health
def test_4_gemini_401_error_classification():
    """Verify 401 / UNAUTHENTICATED / ACCESS_TOKEN_TYPE_UNSUPPORTED classifies as AUTHENTICATION_ERROR."""
    err = ProviderAuthenticationError("Gemini authentication failed (HTTP 401): ACCESS_TOKEN_TYPE_UNSUPPORTED")
    assert classify_failure(err) == FailureCategory.AUTHENTICATION_ERROR


# 5. Gemini 429 Classification
def test_5_gemini_429_quota_classification():
    """Verify 429 RESOURCE_EXHAUSTED maps to QUOTA_EXHAUSTED."""
    err = ProviderQuotaExceededError("RESOURCE_EXHAUSTED quota exceeded (HTTP 429)")
    assert classify_failure(err) == FailureCategory.QUOTA_EXHAUSTED


# 6. Gemini Streaming Success
def test_6_gemini_streaming_success(req):
    """Verify Gemini stream parses SSE data and sends x-goog-api-key header."""
    provider = GeminiProvider(api_key="AQ.ValidStreamingKey")
    sse_data = (
        b'data: {"candidates": [{"content": {"parts": [{"text": "Streamed "}]}}]}\n\n'
        b'data: {"candidates": [{"content": {"parts": [{"text": "Token"}]}}]}\n\n'
    )
    captured_req = None

    def _mock_urlopen(r, timeout=None):
        nonlocal captured_req
        captured_req = r
        resp = MagicMock()
        resp.__iter__.return_value = sse_data.splitlines(keepends=True)
        resp.__enter__.return_value = resp
        return resp

    with patch("urllib.request.urlopen", side_effect=_mock_urlopen):
        async def _stream():
            return [t async for t in provider.stream(req)]
        tokens = asyncio.run(_stream())

    assert tokens == ["Streamed ", "Token"]
    assert captured_req is not None
    assert captured_req.headers.get("X-goog-api-key") == "AQ.ValidStreamingKey"


# 7. Gemini Streaming 401
def test_7_gemini_streaming_401(req):
    """Verify Gemini streaming encountering 401 raises ProviderAuthenticationError."""
    provider = GeminiProvider(api_key="AQ.InvalidKey")
    http_error = urllib.error.HTTPError(
        url="https://generativelanguage.googleapis.com",
        code=401,
        msg="UNAUTHENTICATED",
        hdrs={},
        fp=io.BytesIO(b'{"error": {"code": 401, "message": "UNAUTHENTICATED"}}'),
    )

    with patch("urllib.request.urlopen", side_effect=http_error):
        async def _stream():
            return [t async for t in provider.stream(req)]
        with pytest.raises(ProviderAuthenticationError):
            asyncio.run(_stream())


# 8. Gemini Streaming 429
def test_8_gemini_streaming_429(req):
    """Verify Gemini streaming encountering 429 raises ProviderQuotaExceededError."""
    provider = GeminiProvider(api_key="AQ.RateLimitedKey")
    http_error = urllib.error.HTTPError(
        url="https://generativelanguage.googleapis.com",
        code=429,
        msg="RESOURCE_EXHAUSTED",
        hdrs={},
        fp=io.BytesIO(b'{"error": {"code": 429, "message": "RESOURCE_EXHAUSTED"}}'),
    )

    with patch("urllib.request.urlopen", side_effect=http_error):
        async def _stream():
            return [t async for t in provider.stream(req)]
        with pytest.raises(ProviderQuotaExceededError):
            asyncio.run(_stream())


# 9. Provider Fallback After 401
def test_9_provider_fallback_after_401(req):
    """Verify that when Gemini encounters 401, router marks AUTH_FAILED with cooldown and falls back to Grok."""
    gemini = MockCandidate("gemini", fail_with=ProviderAuthenticationError("HTTP 401 ACCESS_TOKEN_TYPE_UNSUPPORTED"))
    grok = MockCandidate("xai", response_text="Grok fallback response")
    tracker = ProviderHealthTracker(default_cooldown_seconds=300.0)

    router = ModelRouter(
        providers=[gemini, grok],
        strategy=PriorityFallbackStrategy(["gemini", "xai"]),
        tracker=tracker,
    )

    resp = asyncio.run(router.route(req))
    assert resp.content == "Grok fallback response"
    assert gemini.calls == 1
    assert grok.calls == 1
    # Verify Gemini was marked AUTH_FAILED with active cooldown
    assert tracker.get_status("gemini") == ProviderHealthStatus.AUTH_FAILED
    assert tracker.get_record("gemini").cooldown_until > time.monotonic()


# 10. Provider Fallback After 429
def test_10_provider_fallback_after_429(req):
    """Verify that when Gemini encounters 429, router marks QUOTA_EXHAUSTED and falls back to Grok."""
    gemini = MockCandidate("gemini", fail_with=ProviderQuotaExceededError("HTTP 429 RESOURCE_EXHAUSTED"))
    grok = MockCandidate("xai", response_text="Grok quota fallback")
    tracker = ProviderHealthTracker()

    router = ModelRouter(
        providers=[gemini, grok],
        strategy=PriorityFallbackStrategy(["gemini", "xai"]),
        tracker=tracker,
    )

    resp = asyncio.run(router.route(req))
    assert resp.content == "Grok quota fallback"
    assert tracker.get_status("gemini") == ProviderHealthStatus.QUOTA_EXHAUSTED


# 11. Ollama Unavailable (Connection Refused / Offline)
def test_11_ollama_unavailable_marked_offline_and_skipped():
    """Verify Ollama runtime offline does not crash LYRA and is marked OFFLINE."""
    ollama = MockCandidate("local", fail_with=ProviderError("Local AI runtime unreachable: Connection refused"))
    gemini = MockCandidate("gemini", response_text="Gemini responded while Ollama offline")
    tracker = ProviderHealthTracker()

    router = ModelRouter(
        providers=[ollama, gemini],
        strategy=PriorityFallbackStrategy(["local", "gemini"]),
        tracker=tracker,
    )

    req = AIRequest(messages=[Message(role=Role.USER, content="Hello")])
    resp = asyncio.run(router.route(req))
    assert resp.content == "Gemini responded while Ollama offline"
    assert tracker.get_status("local") == ProviderHealthStatus.OFFLINE


# 12. Grok Fallback
def test_12_grok_fallback_when_gemini_down(req):
    gemini = MockCandidate("gemini", fail_with=ProviderAuthenticationError("401"))
    grok = MockCandidate("xai", response_text="Response from Grok")
    router = ModelRouter(providers=[gemini, grok], strategy=PriorityFallbackStrategy(["gemini", "xai"]))
    resp = asyncio.run(router.route(req))
    assert resp.content == "Response from Grok"


# 13. Groq Fallback
def test_13_groq_fallback_when_grok_down(req):
    grok = MockCandidate("xai", fail_with=ProviderError("xAI offline"))
    groq = MockCandidate("groq", response_text="Response from Groq")
    router = ModelRouter(providers=[grok, groq], strategy=PriorityFallbackStrategy(["xai", "groq"]))
    resp = asyncio.run(router.route(req))
    assert resp.content == "Response from Groq"


# 14. Cerebras Fallback
def test_14_cerebras_fallback(req):
    groq = MockCandidate("groq", fail_with=ProviderError("Groq offline"))
    cerebras = MockCandidate("cerebras", response_text="Response from Cerebras")
    router = ModelRouter(providers=[groq, cerebras], strategy=PriorityFallbackStrategy(["groq", "cerebras"]))
    resp = asyncio.run(router.route(req))
    assert resp.content == "Response from Cerebras"


# 15. OpenRouter Fallback
def test_15_openrouter_fallback(req):
    cerebras = MockCandidate("cerebras", fail_with=ProviderError("Cerebras offline"))
    openrouter = MockCandidate("openrouter", response_text="Response from OpenRouter")
    router = ModelRouter(providers=[cerebras, openrouter], strategy=PriorityFallbackStrategy(["cerebras", "openrouter"]))
    resp = asyncio.run(router.route(req))
    assert resp.content == "Response from OpenRouter"


# 16. All Providers Unavailable (Truthful Notification)
def test_16_all_providers_unavailable(req):
    gemini = MockCandidate("gemini", fail_with=ProviderAuthenticationError("401"))
    grok = MockCandidate("xai", fail_with=ProviderError("503 Service Unavailable"))
    router = ModelRouter(providers=[gemini, grok], strategy=PriorityFallbackStrategy(["gemini", "xai"]))
    orchestrator = CompanionOrchestrator(router=router)

    session = Session()
    reply = asyncio.run(orchestrator.process_turn(session, "What is the meaning of life?"))
    assert "don't currently have an available AI provider" in reply
    assert not reply.startswith("Done.")


# 17. Provider Recovery
def test_17_provider_recovery_after_auth_cooldown():
    """Verify provider marked AUTH_FAILED auto-recovers to AVAILABLE when cooldown expires."""
    tracker = ProviderHealthTracker(default_cooldown_seconds=0.05)
    tracker.record_auth_failed("gemini", cooldown_seconds=0.05)
    assert tracker.get_status("gemini") == ProviderHealthStatus.AUTH_FAILED

    time.sleep(0.06)
    assert tracker.get_status("gemini") == ProviderHealthStatus.AVAILABLE


# 18. Tool Calling After Fallback
def test_18_tool_calling_after_fallback():
    """Verify tool execution succeeds even when Gemini fails and Grok handles the turn."""
    mock_tool = MagicMock()
    mock_tool.name = "filesystem"
    mock_tool.can_handle = MagicMock(return_value=True)
    mock_tool.format_result = MagicMock(return_value="Created folder Projects.")

    async def _mock_exec(r):
        return ToolResult(tool_name="filesystem", success=True, output={"status": "created"})

    mock_executor = MagicMock(spec=ToolExecutor)
    mock_executor.execute = AsyncMock(side_effect=_mock_exec)
    mock_registry = MagicMock(spec=ToolRegistry)
    mock_registry.get.return_value = mock_tool

    gemini = MockCandidate("gemini", fail_with=ProviderAuthenticationError("401"))
    grok = MockCandidate("xai", response_text="Folder created successfully via Grok.")
    router = ModelRouter(providers=[gemini, grok], strategy=PriorityFallbackStrategy(["gemini", "xai"]))

    orchestrator = CompanionOrchestrator(
        router=router,
        tool_registry=mock_registry,
        tool_executor=mock_executor,
        offline_mode=False,
    )

    session = Session()
    reply = asyncio.run(orchestrator.process_turn(session, "create folder Projects"))
    assert "Grok" in reply or "Created folder" in reply
    assert mock_executor.execute.called


# 19. Voice Loop After Fallback
def test_19_voice_loop_after_fallback():
    """Verify conversation loop continues normally after an authentication failover."""
    gemini = MockCandidate("gemini", fail_with=ProviderAuthenticationError("401"))
    grok = MockCandidate("xai", response_text="Turn 1 from Grok")
    router = ModelRouter(providers=[gemini, grok], strategy=PriorityFallbackStrategy(["gemini", "xai"]))
    orchestrator = CompanionOrchestrator(router=router)

    session = Session()
    # Turn 1
    reply1 = asyncio.run(orchestrator.process_turn(session, "Turn 1"))
    assert "Grok" in reply1

    # Turn 2: Gemini is on cooldown, Grok handles directly without crashing
    grok.response_text = "Turn 2 from Grok"
    reply2 = asyncio.run(orchestrator.process_turn(session, "Turn 2"))
    assert "Turn 2" in reply2
