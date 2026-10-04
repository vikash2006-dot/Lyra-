"""Unit tests for LYRA AIProvider abstraction interface."""

import asyncio
import pytest

from lyra.core.exceptions import ProviderError
from lyra.models.messages import (
    AIRequest,
    AIResponse,
    Message,
    Role,
    Usage,
)
from lyra.providers.base import AIProvider


class MockConformingProvider(AIProvider):
    """A minimal conforming provider implementation for testing the contract."""

    def __init__(self, fail_on_generate: bool = False) -> None:
        self._fail_on_generate = fail_on_generate

    @property
    def name(self) -> str:
        return "mock-conforming"

    @property
    def is_configured(self) -> bool:
        return True

    async def generate(self, request: AIRequest) -> AIResponse:
        if self._fail_on_generate:
            raise ProviderError("Simulated upstream provider failure.")

        last_user_msg = request.messages[-1].content
        return AIResponse(
            content=f"Echo: {last_user_msg}",
            model=request.model or "mock-default-model",
            role=Role.ASSISTANT,
            finish_reason="stop",
            usage=Usage(prompt_tokens=10, completion_tokens=5),
        )


def test_cannot_instantiate_abstract_provider() -> None:
    """Verify that AIProvider cannot be instantiated directly."""
    with pytest.raises(TypeError, match="Can't instantiate abstract class"):
        AIProvider()  # type: ignore[abstract]


def test_conforming_provider_async_generate() -> None:
    """Verify that a conforming provider can asynchronously generate a valid response."""
    provider = MockConformingProvider()
    request = AIRequest(
        messages=[Message(role=Role.USER, content="Hello World")],
        model="mock-v1",
    )

    async def _run() -> AIResponse:
        return await provider.generate(request)

    response = asyncio.run(_run())

    assert isinstance(response, AIResponse)
    assert response.content == "Echo: Hello World"
    assert response.model == "mock-v1"
    assert response.role == Role.ASSISTANT
    assert response.finish_reason == "stop"
    assert response.usage is not None
    assert response.usage.total_tokens == 15


def test_conforming_provider_sync_generate() -> None:
    """Verify that generate_sync() provides synchronous execution of generate()."""
    provider = MockConformingProvider()
    request = AIRequest(
        messages=[Message(role=Role.USER, content="Synchronous prompt")],
    )

    response = provider.generate_sync(request)

    assert isinstance(response, AIResponse)
    assert response.content == "Echo: Synchronous prompt"
    assert response.model == "mock-default-model"


def test_provider_error_propagation() -> None:
    """Verify that ProviderError is properly raised on provider failure."""
    provider = MockConformingProvider(fail_on_generate=True)
    request = AIRequest(
        messages=[Message(role=Role.USER, content="Will fail")],
    )

    with pytest.raises(ProviderError, match="Simulated upstream provider failure"):
        asyncio.run(provider.generate(request))


def test_stream_default_not_implemented() -> None:
    """Verify that stream() defaults to raising NotImplementedError."""
    provider = MockConformingProvider()
    request = AIRequest(
        messages=[Message(role=Role.USER, content="Stream test")],
    )

    async def _test_stream() -> None:
        async for _ in provider.stream(request):
            pass

    with pytest.raises(NotImplementedError, match="Streaming is not supported"):
        asyncio.run(_test_stream())


def test_health_check_returns_configured_status() -> None:
    """Verify that health_check() returns True and status is READY when configured."""
    provider = MockConformingProvider()
    assert provider.status == "READY"
    assert asyncio.run(provider.health_check()) is True
