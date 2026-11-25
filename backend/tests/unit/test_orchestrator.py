"""Unit tests for LYRA CompanionOrchestrator."""

import asyncio
import pytest

from lyra.companion.orchestrator import (
    UNCONFIGURED_ASSISTANCE_MESSAGE,
    CompanionOrchestrator,
)
from lyra.companion.session import Session
from lyra.core.exceptions import (
    ModelValidationError,
    NoAvailableProviderError,
    ProviderError,
)
from lyra.models.messages import AIRequest, AIResponse, Role
from lyra.providers.base import AIProvider
from lyra.routing.router import ModelRouter


class MockWorkingProvider(AIProvider):
    @property
    def name(self) -> str:
        return "mock-working"

    @property
    def is_configured(self) -> bool:
        return True

    async def generate(self, request: AIRequest) -> AIResponse:
        last_user = request.messages[-1].content
        return AIResponse(
            content=f"LYRA answers: {last_user}",
            model="mock-v1",
            role=Role.ASSISTANT,
        )


class MockFailingProvider(AIProvider):
    @property
    def name(self) -> str:
        return "mock-failing"

    @property
    def is_configured(self) -> bool:
        return True

    async def generate(self, request: AIRequest) -> AIResponse:
        raise ProviderError("Upstream server failure.")


def test_orchestrator_individual_stages() -> None:
    """Verify each discrete stage of the orchestrator pipeline."""
    router = ModelRouter(providers=[MockWorkingProvider()])
    orchestrator = CompanionOrchestrator(router=router)
    session = Session()

    # Stage 1: Input handling
    clean_text = orchestrator.handle_input("  Hello LYRA!  ")
    assert clean_text == "Hello LYRA!"

    # Stage 2: Context preparation
    req = orchestrator.prepare_context(session, clean_text)
    assert len(req.messages) == 1
    assert req.messages[0].content == "Hello LYRA!"
    assert len(session.messages) == 1  # Session now holds the user message

    # Stage 3: Generation
    response = asyncio.run(orchestrator.execute_generation(req))
    assert response.content == "LYRA answers: Hello LYRA!"

    # Stage 4: Response handling
    reply_text = orchestrator.handle_response(session, response)
    assert reply_text == "LYRA answers: Hello LYRA!"
    assert len(session.messages) == 2  # Session now holds user + assistant


def test_orchestrator_full_turn_success() -> None:
    """Verify full process_turn execution."""
    router = ModelRouter(providers=[MockWorkingProvider()])
    orchestrator = CompanionOrchestrator(router=router)
    session = Session()

    reply = asyncio.run(orchestrator.process_turn(session, "What is your purpose?"))

    assert reply == "LYRA answers: What is your purpose?"
    assert len(session.messages) == 2
    assert session.messages[0].content == "What is your purpose?"
    assert session.messages[1].content == "LYRA answers: What is your purpose?"


def test_orchestrator_sync_turn() -> None:
    """Verify synchronous process_turn_sync execution."""
    router = ModelRouter(providers=[MockWorkingProvider()])
    orchestrator = CompanionOrchestrator(router=router)
    session = Session()

    reply = orchestrator.process_turn_sync(session, "Testing synchronous turn")
    assert "Testing synchronous turn" in reply


def test_orchestrator_empty_input_handling() -> None:
    """Verify that empty or whitespace inputs return validation guidance without crashing."""
    router = ModelRouter(providers=[MockWorkingProvider()])
    orchestrator = CompanionOrchestrator(router=router)
    session = Session()

    reply = orchestrator.process_turn_sync(session, "   ")
    assert "Input Error:" in reply
    assert len(session.messages) == 0


def test_orchestrator_no_configured_providers_safety() -> None:
    """Verify that when no providers are configured, LYRA does not crash and returns friendly guidance."""
    router = ModelRouter(providers=[])  # Empty pool
    orchestrator = CompanionOrchestrator(router=router)
    session = Session()

    reply = orchestrator.process_turn_sync(session, "Hello LYRA")

    assert reply == UNCONFIGURED_ASSISTANCE_MESSAGE
    assert "without any configured AI providers" in reply
    assert len(session.messages) == 2  # User message + assistant explanation


def test_orchestrator_provider_failure_safety() -> None:
    """Verify that provider failure returns polite error explanation without crashing."""
    router = ModelRouter(providers=[MockFailingProvider()])
    orchestrator = CompanionOrchestrator(router=router)
    session = Session()

    reply = orchestrator.process_turn_sync(session, "Will fail")

    assert (
        "encountered an error communicating with the AI service" in reply
        or "don't currently have an available AI provider" in reply
    )
    assert len(session.messages) == 2


def test_orchestrator_tool_execution_offline() -> None:
    """Verify orchestrator executes registered tool and formats result when unconfigured/offline."""
    from datetime import datetime, timezone
    from lyra.tools.executor import ToolExecutor
    from lyra.tools.registry import ToolRegistry
    from lyra.tools.time_tool import TimeTool

    fixed_time = datetime(2026, 9, 12, 14, 30, 0, tzinfo=timezone.utc)
    time_tool = TimeTool(clock_fn=lambda: fixed_time)
    registry = ToolRegistry(tools=[time_tool])
    executor = ToolExecutor(registry=registry)

    # Empty provider pool (offline)
    router = ModelRouter(providers=[])
    orchestrator = CompanionOrchestrator(
        router=router,
        tool_registry=registry,
        tool_executor=executor,
    )
    session = Session()

    reply = orchestrator.process_turn_sync(session, "What time is it?")

    assert "The current time is" in reply
    assert "2:30 PM" in reply
    assert "Saturday, September 12, 2026" in reply
    assert len(session.messages) == 2
    assert session.messages[0].content == "What time is it?"
    assert session.messages[1].metadata.get("tool_name") == "time"
    assert session.messages[1].metadata.get("tool_success") is True


def test_orchestrator_tool_execution_with_ai_synthesis() -> None:
    """Verify orchestrator runs tool and delegates synthesis to AI provider when configured."""
    from datetime import datetime, timezone
    from lyra.tools.executor import ToolExecutor
    from lyra.tools.registry import ToolRegistry
    from lyra.tools.time_tool import TimeTool

    fixed_time = datetime(2026, 9, 12, 14, 30, 0, tzinfo=timezone.utc)
    time_tool = TimeTool(clock_fn=lambda: fixed_time)
    registry = ToolRegistry(tools=[time_tool])
    executor = ToolExecutor(registry=registry)

    router = ModelRouter(providers=[MockWorkingProvider()])
    orchestrator = CompanionOrchestrator(
        router=router,
        tool_registry=registry,
        tool_executor=executor,
    )
    session = Session()

    reply = orchestrator.process_turn_sync(session, "What time is it?")

    # MockWorkingProvider returns "LYRA answers: <augmented prompt>"
    assert "LYRA answers:" in reply
    assert '<untrusted_external_content source="time">' in reply
    assert "SECURITY NOTICE:" in reply
    assert len(session.messages) == 2
    assert session.messages[0].content == "What time is it?"


def test_orchestrator_memory_context_injection(tmp_path) -> None:
    """Verify orchestrator injects long-term memory summary into system prompt."""
    from lyra.memory.manager import MemoryManager
    from lyra.memory.sqlite_repository import SQLiteMemoryRepository
    from lyra.models.memory import MemoryType

    repo = SQLiteMemoryRepository(db_path=str(tmp_path / "test_orch_mem.db"))
    mgr = MemoryManager(repository=repo)
    mgr.remember(
        user_id="alice",
        content="Prefers dark mode and concise responses",
        memory_type=MemoryType.PREFERENCE,
    )

    router = ModelRouter(providers=[MockWorkingProvider()])
    orchestrator = CompanionOrchestrator(router=router, memory_manager=mgr)

    session_alice = Session(user_id="alice")
    req = orchestrator.prepare_context(session_alice, "Hello!")

    assert "User Long-Term Memory:" in req.system_prompt
    assert "[preference] Prefers dark mode and concise responses" in req.system_prompt

    # User Bob does not have Alice's memories
    session_bob = Session(user_id="bob")
    req_bob = orchestrator.prepare_context(session_bob, "Hello!")
    assert "User Long-Term Memory:" not in req_bob.system_prompt

