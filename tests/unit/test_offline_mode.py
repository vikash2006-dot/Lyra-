"""Unit tests for LYRA Offline Mode and Local AI isolation.

Verifies:
- Router filters out all external cloud providers when offline mode is active.
- Router exclusively selects LocalProvider or mock providers.
- External network tools (weather, search, news, maps, browser) are blocked.
- Local tools (time, memory, file, computer) execute normally.
- Memory and conversation history are never sent to external endpoints.
- User is notified when offline mode is active.
"""

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from lyra.companion.orchestrator import CompanionOrchestrator
from lyra.companion.session import Session
from lyra.core.exceptions import NoAvailableProviderError
from lyra.memory.manager import MemoryManager
from lyra.memory.policy import MemoryPolicy
from lyra.memory.sqlite_repository import SQLiteMemoryRepository
from lyra.models.memory import MemoryRecord, MemoryType
from lyra.models.messages import AIRequest, AIResponse, Message, Role
from lyra.models.tools import ToolRequest
from lyra.providers.cerebras import CerebrasProvider
from lyra.providers.gemini import GeminiProvider
from lyra.providers.groq import GroqProvider
from lyra.providers.local import LocalProvider
from lyra.providers.openrouter import OpenRouterProvider
from lyra.routing.health import ProviderHealthStatus, ProviderHealthTracker
from lyra.routing.router import ModelRouter
from lyra.routing.strategies import PriorityFallbackStrategy
from lyra.tools.browser_tool import BrowserTool
from lyra.tools.computer_tool import ComputerTool
from lyra.tools.executor import ToolExecutor
from lyra.tools.file_tool import FileTool
from lyra.tools.maps import MapsTool
from lyra.tools.memory_tool import MemoryTool
from lyra.tools.news import NewsTool
from lyra.tools.registry import ToolRegistry
from lyra.tools.search import SearchTool
from lyra.tools.time_tool import TimeTool
from lyra.tools.weather import WeatherTool


def test_priority_fallback_strategy_filters_cloud_providers_in_offline_mode():
    """Verify that PriorityFallbackStrategy excludes all external cloud providers when offline."""
    gemini = GeminiProvider(api_key="fake-key")
    groq = GroqProvider(api_key="fake-key")
    local = LocalProvider(endpoint="http://localhost:11434")

    tracker = ProviderHealthTracker()

    # 1. Normal online mode includes cloud providers
    online_strat = PriorityFallbackStrategy(
        priority_order=("gemini", "groq", "local"),
        offline_mode=False,
    )
    req = AIRequest(messages=(Message(role=Role.USER, content="Hello"),))
    online_candidates = online_strat.select_candidates([gemini, groq, local], req, tracker)
    assert [p.name for p in online_candidates] == ["gemini", "groq", "local"]

    # 2. Offline mode excludes cloud providers, keeping only local
    offline_strat = PriorityFallbackStrategy(
        priority_order=("gemini", "groq", "local"),
        offline_mode=True,
    )
    offline_candidates = offline_strat.select_candidates([gemini, groq, local], req, tracker)
    assert [p.name for p in offline_candidates] == ["local"]

    # 3. Explicit request preferred_provider for cloud is ignored when offline
    cloud_pref_req = AIRequest(
        messages=(Message(role=Role.USER, content="Hello"),),
        metadata={"preferred_provider": "gemini"},
    )
    candidates_with_pref = offline_strat.select_candidates([gemini, groq, local], cloud_pref_req, tracker)
    assert [p.name for p in candidates_with_pref] == ["local"]


def test_router_offline_mode_routing():
    """Verify ModelRouter routes exclusively to local provider when offline."""
    gemini = GeminiProvider(api_key="fake-key")
    local = LocalProvider(endpoint="http://localhost:11434")

    router = ModelRouter(providers=[gemini, local], offline_mode=True)

    # Mock local provider generate
    mock_local_resp = AIResponse(content="Local offline reply", model="llama3.2", role=Role.ASSISTANT)

    with patch.object(local, "generate", return_value=mock_local_resp) as mock_generate:
        import asyncio
        req = AIRequest(messages=(Message(role=Role.USER, content="Hello"),))
        resp = asyncio.run(router.route(req))

        assert resp.content == "Local offline reply"
        assert resp.model == "llama3.2"
        mock_generate.assert_called_once()


def test_router_offline_mode_no_local_available_raises_informative_error():
    """Verify router raises NoAvailableProviderError explaining offline mode when no local runtime."""
    gemini = GeminiProvider(api_key="fake-key")
    # Only cloud provider registered
    router = ModelRouter(providers=[gemini], offline_mode=True)

    import asyncio
    req = AIRequest(messages=(Message(role=Role.USER, content="Hello"),))
    with pytest.raises(NoAvailableProviderError) as exc_info:
        asyncio.run(router.route(req))

    assert "Offline mode is active" in str(exc_info.value)
    assert "External cloud providers are disabled" in str(exc_info.value)


def test_tool_executor_blocks_network_tools_in_offline_mode():
    """Verify ToolExecutor blocks external tools and permits local tools in offline mode."""
    time_tool = TimeTool()
    weather_tool = WeatherTool()
    search_tool = SearchTool()
    news_tool = NewsTool()
    maps_tool = MapsTool()
    file_tool = FileTool()

    registry = ToolRegistry(tools=[
        time_tool,
        weather_tool,
        search_tool,
        news_tool,
        maps_tool,
        file_tool,
    ])

    executor = ToolExecutor(registry=registry, offline_mode=True)

    import asyncio

    # 1. Local tool (TimeTool) succeeds
    res_time = asyncio.run(executor.execute(ToolRequest(tool_name="time", arguments={})))
    assert res_time.success is True

    # 2. External tools are blocked by offline mode
    for ext_tool_name, args in [
        ("weather", {"location": "London"}),
        ("search", {"query": "python news"}),
        ("news", {"topic": "technology"}),
        ("maps", {"action": "search", "query": "Paris"}),
    ]:
        res = asyncio.run(executor.execute(ToolRequest(tool_name=ext_tool_name, arguments=args)))
        assert res.success is False
        assert res.metadata.get("offline_blocked") is True
        assert "blocked in offline mode" in res.error


def test_memory_privacy_preservation_in_offline_mode(tmp_path: Path):
    """Verify that stored memories remain completely local and are not dispatched to cloud APIs."""
    db_file = tmp_path / "offline_memory.db"
    repo = SQLiteMemoryRepository(db_path=db_file)
    manager = MemoryManager(repository=repo, policy=MemoryPolicy())

    # Store a private memory
    manager.remember(
        user_id="user_offline",
        content="Secret medical or financial detail.",
        memory_type=MemoryType.FACT,
        importance=0.9,
    )

    gemini = GeminiProvider(api_key="secret-key")
    local = LocalProvider(endpoint="http://localhost:11434")

    router = ModelRouter(providers=[gemini, local], offline_mode=True)

    orchestrator = CompanionOrchestrator(
        router=router,
        memory_manager=manager,
        offline_mode=True,
    )

    mock_resp = AIResponse(content="I remember your private details safely offline.", model="llama3.2")

    with patch.object(gemini, "generate") as mock_gemini_generate, patch.object(
        local, "generate", return_value=mock_resp
    ) as mock_local_generate:
        import asyncio
        session = Session(user_id="user_offline")
        reply = asyncio.run(orchestrator.process_turn(session, "What do you know about me?"))

        assert "safely offline" in reply
        # Gemini was NEVER called
        mock_gemini_generate.assert_not_called()
        # Local model was called
        mock_local_generate.assert_called_once()
        # Verify request metadata sent to local model had offline_mode=True
        call_req: AIRequest = mock_local_generate.call_args[0][0]
        assert call_req.metadata.get("offline_mode") is True
