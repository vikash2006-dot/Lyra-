"""Unit tests for CompanionOrchestrator stream_turn conversational interaction."""

import asyncio
from collections.abc import AsyncIterator
import pytest

from lyra.companion.orchestrator import CompanionOrchestrator
from lyra.companion.session import Session
from lyra.models.messages import AIRequest, AIResponse
from lyra.models.stream import CancellationToken, StreamCompleted, StreamStarted, TextDelta
from lyra.providers.base import AIProvider
from lyra.routing.router import ModelRouter
from lyra.tools.executor import ToolExecutor
from lyra.tools.registry import ToolRegistry
from lyra.tools.time_tool import TimeTool


class MockStreamer(AIProvider):
    def __init__(self, name: str = "mock-stream", tokens: list[str] | None = None):
        self._name = name
        self.tokens = tokens or ["Streaming", " companion", " response", "."]

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
        for t in self.tokens:
            await asyncio.sleep(0.01)
            yield t


def test_orchestrator_stream_turn_full_flow():
    provider = MockStreamer()
    router = ModelRouter(providers=[provider])
    orchestrator = CompanionOrchestrator(router=router)
    session = Session()

    events = []

    async def _run():
        async for event in orchestrator.stream_turn(session, "Tell me a story"):
            events.append(event)

    asyncio.run(_run())

    assert len(events) >= 3
    assert isinstance(events[0], StreamStarted)
    deltas = [e.delta for e in events if isinstance(e, TextDelta)]
    assert deltas == ["Streaming", " companion", " response", "."]

    # Session message history is updated
    assert len(session.messages) == 2
    assert session.messages[0].content == "Tell me a story"
    assert session.messages[1].content == "Streaming companion response."


def test_orchestrator_stream_turn_tool_execution():
    time_tool = TimeTool()
    registry = ToolRegistry(tools=[time_tool])
    executor = ToolExecutor(registry=registry)

    # Without configured provider, offline tool presentation streams as single token
    router = ModelRouter(providers=[])
    orchestrator = CompanionOrchestrator(
        router=router,
        tool_registry=registry,
        tool_executor=executor,
    )
    session = Session()

    events = []

    async def _run():
        async for event in orchestrator.stream_turn(session, "what time is it?"):
            events.append(event)

    asyncio.run(_run())

    assert len(events) == 3  # Started, TextDelta, Completed
    assert isinstance(events[0], StreamStarted)
    assert events[0].provider == "tool"
    assert isinstance(events[1], TextDelta)
    assert "The current time is" in events[1].delta
    assert len(session.messages) == 2


def test_orchestrator_stream_turn_unconfigured():
    router = ModelRouter(providers=[])
    orchestrator = CompanionOrchestrator(router=router)
    session = Session()

    events = []

    async def _run():
        async for event in orchestrator.stream_turn(session, "hello"):
            events.append(event)

    asyncio.run(_run())

    deltas = [e.delta for e in events if isinstance(e, TextDelta)]
    assert len(deltas) == 1
    assert "running without any configured AI providers" in deltas[0]
