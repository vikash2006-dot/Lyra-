"""Unit tests for LYRA Intelligent Model Router."""

import asyncio
from unittest.mock import MagicMock
import pytest

from lyra.core.exceptions import (
    NoAvailableProviderError,
    ProviderAuthenticationError,
    ProviderError,
    ProviderRateLimitError,
)
from lyra.models.messages import AIRequest, AIResponse, Message, Role
from lyra.providers.base import AIProvider
from lyra.routing.health import ProviderHealthStatus, ProviderHealthTracker
from lyra.routing.router import ModelRouter
from lyra.routing.strategies import PriorityFallbackStrategy


class StubProvider(AIProvider):
    """Stub AIProvider for testing routing behaviors."""

    def __init__(
        self,
        name: str,
        is_configured: bool = True,
        fail_with: Exception | None = None,
        return_content: str | None = None,
    ) -> None:
        self._name = name
        self._is_configured = is_configured
        self._fail_with = fail_with
        self._return_content = return_content or f"Response from {name}"
        self.call_count = 0

    @property
    def name(self) -> str:
        return self._name

    @property
    def is_configured(self) -> bool:
        return self._is_configured

    async def generate(self, request: AIRequest) -> AIResponse:
        self.call_count += 1
        if self._fail_with:
            raise self._fail_with
        return AIResponse(
            content=self._return_content,
            model=f"{self._name}-test-model",
            role=Role.ASSISTANT,
        )


@pytest.fixture
def base_request() -> AIRequest:
    return AIRequest(
        messages=[Message(role=Role.USER, content="Hello Router")],
    )


def test_priority_order_routing(base_request: AIRequest) -> None:
    """Verify that router tries providers in configured priority order."""
    gemini = StubProvider("gemini")
    groq = StubProvider("groq")
    openrouter = StubProvider("openrouter")
    cerebras = StubProvider("cerebras")

    router = ModelRouter(
        providers=[cerebras, openrouter, groq, gemini],
        strategy=PriorityFallbackStrategy(["gemini", "groq", "openrouter", "cerebras"]),
    )

    response = asyncio.run(router.route(base_request))

    # Gemini was first in priority, so it should answer
    assert response.content == "Response from gemini"
    assert gemini.call_count == 1
    assert groq.call_count == 0
    assert openrouter.call_count == 0
    assert cerebras.call_count == 0


def test_user_preference_override(base_request: AIRequest) -> None:
    """Verify that user preference in metadata takes top priority."""
    gemini = StubProvider("gemini")
    cerebras = StubProvider("cerebras")

    router = ModelRouter(
        providers=[gemini, cerebras],
        strategy=PriorityFallbackStrategy(["gemini", "cerebras"]),
    )

    # Request specifying preference for cerebras
    req_with_pref = AIRequest(
        messages=base_request.messages,
        metadata={"preferred_provider": "cerebras"},
    )

    response = asyncio.run(router.route(req_with_pref))

    assert response.content == "Response from cerebras"
    assert cerebras.call_count == 1
    assert gemini.call_count == 0


def test_fallback_on_provider_failure(base_request: AIRequest) -> None:
    """Verify cascading fallback when top-priority provider fails."""
    gemini = StubProvider("gemini", fail_with=ProviderError("Gemini server 500 error"))
    groq = StubProvider("groq", return_content="Groq fallback answer")

    router = ModelRouter(
        providers=[gemini, groq],
        strategy=PriorityFallbackStrategy(["gemini", "groq"]),
    )

    response = asyncio.run(router.route(base_request))

    assert response.content == "Groq fallback answer"
    assert gemini.call_count == 1
    assert groq.call_count == 1
    assert router.get_provider_status("gemini") == ProviderHealthStatus.UNAVAILABLE
    assert router.get_provider_status("groq") == ProviderHealthStatus.AVAILABLE


def test_fallback_on_rate_limit(base_request: AIRequest) -> None:
    """Verify rate-limited provider transitions to RATE_LIMITED and triggers fallback."""
    gemini = StubProvider("gemini", fail_with=ProviderRateLimitError("429 Too Many Requests"))
    openrouter = StubProvider("openrouter", return_content="OpenRouter fallback answer")

    router = ModelRouter(
        providers=[gemini, openrouter],
        strategy=PriorityFallbackStrategy(["gemini", "openrouter"]),
    )

    response = asyncio.run(router.route(base_request))

    assert response.content == "OpenRouter fallback answer"
    assert gemini.call_count == 1
    assert openrouter.call_count == 1
    assert router.get_provider_status("gemini") == ProviderHealthStatus.RATE_LIMITED
    assert router.get_provider_status("openrouter") == ProviderHealthStatus.AVAILABLE


def test_unconfigured_providers_are_skipped(base_request: AIRequest) -> None:
    """Verify that unconfigured providers (NOT_CONFIGURED) are never selected."""
    gemini = StubProvider("gemini", is_configured=False)
    groq = StubProvider("groq", is_configured=True, return_content="Groq answer")

    router = ModelRouter(
        providers=[gemini, groq],
        strategy=PriorityFallbackStrategy(["gemini", "groq"]),
    )

    assert router.get_provider_status("gemini") == ProviderHealthStatus.NOT_CONFIGURED

    response = asyncio.run(router.route(base_request))

    assert response.content == "Groq answer"
    assert gemini.call_count == 0
    assert groq.call_count == 1


def test_all_providers_unavailable_raises_error(base_request: AIRequest) -> None:
    """Verify NoAvailableProviderError is raised when all providers fail."""
    gemini = StubProvider("gemini", fail_with=ProviderError("Gemini down"))
    groq = StubProvider("groq", fail_with=ProviderAuthenticationError("Invalid API key"))

    router = ModelRouter(
        providers=[gemini, groq],
        strategy=PriorityFallbackStrategy(["gemini", "groq"]),
    )

    with pytest.raises(NoAvailableProviderError, match="All candidate providers failed"):
        asyncio.run(router.route(base_request))


def test_empty_provider_pool_raises_error(base_request: AIRequest) -> None:
    """Verify NoAvailableProviderError when no providers are configured or registered."""
    router = ModelRouter(providers=[])

    with pytest.raises(NoAvailableProviderError, match="No available AI provider"):
        asyncio.run(router.route(base_request))


def test_rate_limit_cooldown_recovery() -> None:
    """Verify that rate-limited provider recovers to AVAILABLE after cooldown expires."""
    tracker = ProviderHealthTracker(default_cooldown_seconds=0.05)
    mock_prov = StubProvider("gemini", is_configured=True)

    tracker.record_rate_limited("gemini")
    assert tracker.get_status(mock_prov) == ProviderHealthStatus.RATE_LIMITED

    # Wait for cooldown to expire
    import time
    time.sleep(0.06)

    assert tracker.get_status(mock_prov) == ProviderHealthStatus.AVAILABLE


def test_sync_routing_wrapper(base_request: AIRequest) -> None:
    """Verify route_sync() functions identically to async route()."""
    groq = StubProvider("groq", return_content="Sync test answer")
    router = ModelRouter(providers=[groq])

    response = router.route_sync(base_request)
    assert response.content == "Sync test answer"
