"""Unit tests for LYRA streaming event abstractions, capabilities, and cancellation."""

import asyncio
from collections.abc import AsyncIterator
import pytest

from lyra.core.exceptions import (
    NoAvailableProviderError,
    ProviderError,
    StreamInterruptedError,
    UnsupportedCapabilityError,
)
from lyra.models.capabilities import ProviderCapability
from lyra.models.messages import AIRequest, AIResponse, Message, Role
from lyra.models.stream import (
    CancellationToken,
    StreamChunk,
    StreamCompleted,
    StreamError,
    StreamStarted,
    TextDelta,
)
from lyra.providers.base import AIProvider
from lyra.routing.router import ModelRouter


class MockStreamingProvider(AIProvider):
    def __init__(self, name: str = "mock-streamer", tokens: list[str] | None = None, fail_midway: bool = False):
        self._name = name
        self.tokens = tokens or ["Hello", " world", "!"]
        self.fail_midway = fail_midway

    @property
    def name(self) -> str:
        return self._name

    @property
    def is_configured(self) -> bool:
        return True

    @property
    def supports_streaming(self) -> bool:
        return True

    async def generate(self, request: AIRequest) -> AIResponse:
        return AIResponse(content="".join(self.tokens), model="mock-model")

    async def stream(self, request: AIRequest) -> AsyncIterator[str]:
        for idx, token in enumerate(self.tokens):
            if self.fail_midway and idx == 1:
                raise ProviderError("Connection dropped mid-stream.")
            await asyncio.sleep(0.01)
            yield token


class MockNonStreamingProvider(AIProvider):
    @property
    def name(self) -> str:
        return "non-streamer"

    @property
    def is_configured(self) -> bool:
        return True

    @property
    def supports_streaming(self) -> bool:
        return False

    async def generate(self, request: AIRequest) -> AIResponse:
        return AIResponse(content="Full response", model="batch-model")


def test_stream_event_types():
    started = StreamStarted(provider="gemini", model="gemini-2.0-flash")
    assert started.provider == "gemini"
    assert started.model == "gemini-2.0-flash"

    delta = TextDelta(delta="token", index=2)
    assert delta.delta == "token"
    assert delta.index == 2

    completed = StreamCompleted(full_text="token", finish_reason="stop")
    assert completed.full_text == "token"

    err = StreamError(error_message="Network lost")
    assert err.error_message == "Network lost"
    assert err.recoverable is False


def test_cancellation_token():
    token = CancellationToken()
    assert token.is_cancelled is False
    token.check_cancelled()  # Does not raise

    token.cancel("User requested stop")
    assert token.is_cancelled is True
    assert token.reason == "User requested stop"

    with pytest.raises(StreamInterruptedError, match="User requested stop"):
        token.check_cancelled()


def test_provider_capability_taxonomy():
    assert ProviderCapability.from_str("streaming") == ProviderCapability.STREAMING
    assert ProviderCapability.from_str("image_understanding") == ProviderCapability.IMAGE_UNDERSTANDING
    assert ProviderCapability.from_str("document-understanding") == ProviderCapability.DOCUMENT_UNDERSTANDING

    provider = MockStreamingProvider()
    assert provider.has_capability(ProviderCapability.STREAMING) is True
    assert provider.has_capability(ProviderCapability.TEXT_GENERATION) is True
    assert provider.has_capability(ProviderCapability.IMAGE_UNDERSTANDING) is False

    non_streamer = MockNonStreamingProvider()
    assert non_streamer.has_capability(ProviderCapability.STREAMING) is False


def test_provider_stream_events_flow():
    provider = MockStreamingProvider(tokens=["A", "B", "C"])
    req = AIRequest(messages=[Message(role=Role.USER, content="hi")])

    events = []

    async def _run():
        async for event in provider.stream_events(req):
            events.append(event)

    asyncio.run(_run())

    assert len(events) == 5  # Started, 3 TextDelta, Completed
    assert isinstance(events[0], StreamStarted)
    assert isinstance(events[1], TextDelta)
    assert events[1].delta == "A"
    assert isinstance(events[4], StreamCompleted)
    assert events[4].full_text == "ABC"


def test_provider_stream_events_cancellation():
    provider = MockStreamingProvider(tokens=["Token1", "Token2", "Token3"])
    token = CancellationToken()
    req = AIRequest(messages=[Message(role=Role.USER, content="hi")])

    events = []

    async def _run():
        async for event in provider.stream_events(req, cancellation_token=token):
            events.append(event)
            token.cancel("User interrupted")

    with pytest.raises(StreamInterruptedError):
        asyncio.run(_run())

    assert len(events) >= 1
    assert isinstance(events[0], StreamStarted)


def test_non_streaming_provider_raises_unsupported_capability():
    provider = MockNonStreamingProvider()
    req = AIRequest(messages=[Message(role=Role.USER, content="hi")])

    async def _run():
        async for _ in provider.stream_events(req):
            pass

    with pytest.raises(UnsupportedCapabilityError):
        asyncio.run(_run())


def test_router_stream_events_fallback():
    # First provider fails immediately, second succeeds
    failing = MockStreamingProvider(name="failing", tokens=[], fail_midway=True)
    # Give it a failure on first iteration
    async def fail_stream(req):
        raise ProviderError("Early connection drop")
        yield ""
    failing.stream = fail_stream

    working = MockStreamingProvider(name="working", tokens=["Fallback", " OK"])
    router = ModelRouter(providers=[failing, working])

    req = AIRequest(messages=[Message(role=Role.USER, content="hi")])

    events = []

    async def _run():
        async for event in router.stream_events(req):
            events.append(event)

    asyncio.run(_run())

    deltas = [e.delta for e in events if isinstance(e, TextDelta)]
    assert deltas == ["Fallback", " OK"]
