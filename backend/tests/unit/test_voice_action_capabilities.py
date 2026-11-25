"""Unit tests for the 25 universal voice action capabilities in Lyra.

Covers:
1. Increase brightness
2. Decrease brightness
3. Make screen darker
4. Make screen brighter
5. Open Finder
6. Open Chrome
7. Create folder on Desktop
8. Create file
9. Open YouTube
10. Search YouTube
11. Play first YouTube result
12. Open new tab
13. Search Google
14. Open first search result
15. Switch tabs
16. Close tab
17. Increase volume
18. Mute
19. Multi-step browser task (open YouTube, search, play)
20. Multi-step filesystem task (create folder and file inside)
21. Context-dependent sequence across turns
22. Failed tool reporting (truthful, no false "Done")
23. Confirmation-required operation (destructive delete)
24. Gemini 429 quota fallback
25. Voice -> Action -> TTS pipeline end-to-end simulation
"""

import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock
import pytest

from lyra.companion.orchestrator import CompanionOrchestrator
from lyra.companion.planner import ActionPlanner
from lyra.companion.session import Session
from lyra.core.capabilities import Capability, CapabilityRegistry
from lyra.models.messages import AIRequest, AIResponse
from lyra.models.tools import ToolRequest, ToolResult
from lyra.routing.router import ModelRouter
from lyra.routing.strategies import PriorityFallbackStrategy
from lyra.tools.browser_tool import BrowserTool
from lyra.tools.executor import ToolExecutor
from lyra.tools.filesystem import FilesystemTool
from lyra.tools.registry import ToolRegistry
from lyra.tools.system_tool import SystemTool


@pytest.fixture
def planner():
    return ActionPlanner()


@pytest.fixture
def session():
    return Session()


# 1. Increase brightness
def test_capability_01_increase_brightness(planner, session):
    plan = planner.plan("Lyra, increase the brightness", session=session)
    assert plan is not None
    assert "system" in plan.tool_name
    assert "brightness" in plan.arguments.get("action")
    assert plan.arguments.get("delta") > 0


# 2. Decrease brightness
def test_capability_02_decrease_brightness(planner, session):
    plan = planner.plan("Lyra, decrease the brightness", session=session)
    assert plan is not None
    assert "system" in plan.tool_name
    assert "brightness" in plan.arguments.get("action")
    assert plan.arguments.get("delta") == 0.1


# 3. Make screen darker
def test_capability_03_make_screen_darker(planner, session):
    plan = planner.plan("make screen darker", session=session)
    assert plan is not None
    assert "system" in plan.tool_name
    assert "brightness" in plan.arguments.get("action")
    assert plan.arguments.get("delta") == 0.1


# 4. Make screen brighter
def test_capability_04_make_screen_brighter(planner, session):
    plan = planner.plan("make screen brighter", session=session)
    assert plan is not None
    assert "system" in plan.tool_name
    assert "brightness" in plan.arguments.get("action")
    assert plan.arguments.get("delta") > 0


# 5. Open Finder
def test_capability_05_open_finder(planner, session):
    plan = planner.plan("open Finder", session=session)
    assert plan is not None
    assert "launch_app" in plan.tool_name or "system" in plan.tool_name
    assert plan.arguments.get("app_name") == "Finder"


# 6. Open Chrome
def test_capability_06_open_chrome(planner, session):
    plan = planner.plan("open Google Chrome", session=session)
    assert plan is not None
    assert "launch_app" in plan.tool_name or "system" in plan.tool_name
    assert "Chrome" in plan.arguments.get("app_name")


# 7. Create folder on Desktop
def test_capability_07_create_folder_on_desktop(planner, session):
    plan = planner.plan("create a folder called College on my Desktop", session=session)
    assert plan is not None
    assert "filesystem" in plan.tool_name
    assert "Desktop" in plan.arguments.get("path")
    assert "College" in plan.arguments.get("path")


# 8. Create file
def test_capability_08_create_file(planner, session):
    plan = planner.plan("create a file named notes.txt with hello world", session=session)
    assert plan is not None
    assert "filesystem" in plan.tool_name
    assert "notes.txt" in plan.arguments.get("path")
    assert plan.arguments.get("content") == "hello world"


# 9. Open YouTube
def test_capability_09_open_youtube(planner, session):
    plan = planner.plan("open YouTube", session=session)
    assert plan is not None
    assert "browser" in plan.tool_name
    assert "youtube.com" in plan.arguments.get("url")


# 10. Search YouTube
def test_capability_10_search_youtube(planner, session):
    plan = planner.plan("search YouTube for Arijit Singh", session=session)
    assert plan is not None
    assert "browser" in plan.tool_name
    assert "Arijit Singh" in plan.arguments.get("query")


# 11. Play first YouTube result
def test_capability_11_play_first_youtube_result(planner, session):
    plan = planner.plan("play the first song on YouTube", session=session)
    assert plan is not None
    assert "browser" in plan.tool_name


# 12. Open new tab
def test_capability_12_open_new_tab(planner, session):
    plan = planner.plan("open a new tab", session=session)
    assert plan is not None
    assert "browser" in plan.tool_name
    assert plan.arguments.get("action") == "new_tab"


# 13. Search Google
def test_capability_13_search_google(planner, session):
    plan = planner.plan("search Google for Python tutorials", session=session)
    assert plan is not None
    assert "browser" in plan.tool_name
    assert "Python tutorials" in plan.arguments.get("query")


# 14. Open first search result
def test_capability_14_open_first_search_result(planner, session):
    plan = planner.plan("open the first result", session=session)
    assert plan is not None
    assert "browser" in plan.tool_name
    assert plan.arguments.get("action") == "open_search_result"
    assert plan.arguments.get("index") in (0, 1)


# 15. Switch tabs
def test_capability_15_switch_tabs(planner, session):
    plan = planner.plan("switch to tab 2", session=session)
    assert plan is not None
    assert "browser" in plan.tool_name
    assert plan.arguments.get("action") == "switch_tab"
    assert plan.arguments.get("index") == 2


# 16. Close tab
def test_capability_16_close_tab(planner, session):
    plan = planner.plan("close tab", session=session)
    assert plan is not None
    assert "browser" in plan.tool_name
    assert plan.arguments.get("action") == "close_tab"


# 17. Increase volume
def test_capability_17_increase_volume(planner, session):
    plan = planner.plan("increase the volume", session=session)
    assert plan is not None
    assert "system" in plan.tool_name
    assert "volume" in plan.arguments.get("action")
    assert plan.arguments.get("delta") > 0


# 18. Mute
def test_capability_18_mute(planner, session):
    plan = planner.plan("mute the audio", session=session)
    assert plan is not None
    assert "system" in plan.tool_name
    assert plan.arguments.get("action") == "mute"


# 19. Multi-step browser task
def test_capability_19_multi_step_browser(planner, session):
    plan = planner.plan("open YouTube, search for Arijit Singh, and play the first song", session=session)
    assert plan is not None
    assert len(plan.steps) >= 2
    assert any("search_youtube" in step.tool for step in plan.steps)
    assert any("play_media" in step.tool for step in plan.steps)


# 20. Multi-step filesystem task
def test_capability_20_multi_step_filesystem(planner, session):
    plan = planner.plan("create a folder called College on my desktop, open it, and create a file called notes.txt inside it.", session=session)
    assert plan is not None
    assert len(plan.steps) == 3
    assert "filesystem" in plan.steps[0].tool
    assert "College/notes.txt" in plan.steps[2].arguments["path"]


# 21. Context-dependent sequence across turns
def test_capability_21_context_dependent_sequence(planner, session):
    # Turn 1: Open YouTube
    p1 = planner.plan("Open YouTube", session=session)
    assert p1 is not None

    # Turn 2: Search for Believer
    p2 = planner.plan("Search for Believer", session=session)
    assert p2 is not None
    assert p2.intent == "contextual_youtube_search"
    assert p2.steps[0].arguments["query"] == "Believer"

    # Turn 3: Play the first one
    p3 = planner.plan("Play the first one", session=session)
    assert p3 is not None
    assert p3.intent == "contextual_play_top_result"


# 22. Failed tool reporting (truthful, no false "Done")
def test_capability_22_failed_tool_reporting(session):
    mock_tool = MagicMock()
    mock_tool.name = "system"
    mock_tool.can_handle = MagicMock(return_value=True)

    # Tool execution returns a failure
    async def _mock_execute(req):
        return ToolResult(
            tool_name="system",
            success=False,
            output={},
            error="DisplayServices failed to adjust brightness.",
        )

    mock_executor = MagicMock(spec=ToolExecutor)
    mock_executor.execute = AsyncMock(side_effect=_mock_execute)

    mock_registry = MagicMock(spec=ToolRegistry)
    mock_registry.get.return_value = mock_tool

    strategy = PriorityFallbackStrategy(["local"], offline_mode=True)
    router = ModelRouter(providers=[], strategy=strategy, offline_mode=True)

    orchestrator = CompanionOrchestrator(
        router=router,
        tool_registry=mock_registry,
        tool_executor=mock_executor,
        offline_mode=True,
    )

    response = asyncio.run(orchestrator.process_turn(session, "decrease brightness"))
    # Must NOT report "Done" or success when tool failed
    assert "couldn't complete" in response.lower() or "failed" in response.lower()
    assert not response.startswith("Done.")


# 23. Confirmation-required operation (destructive delete)
def test_capability_23_confirmation_required_delete(planner, session):
    plan = planner.plan("delete folder College", session=session)
    assert plan is not None
    assert plan.requires_confirmation is True


# 24. Gemini 429 quota fallback
def test_capability_24_quota_fallback(session):
    # Mock router that returns fallback generation response
    mock_router = MagicMock(spec=ModelRouter)
    mock_router.list_providers.return_value = []
    mock_router.route = AsyncMock(
        return_value=AIResponse(
            content="Fallback provider answer: Hello!",
            model="groq/llama-3.3-70b",
        )
    )

    orchestrator = CompanionOrchestrator(
        router=mock_router,
        tool_registry=None,
        tool_executor=None,
    )

    # Prompt requiring conversational LLM generation
    res = asyncio.run(orchestrator.process_turn(session, "Tell me a creative haiku about stars"))
    assert mock_router.route.called
    assert "Fallback provider answer" in res


# 25. Voice -> Action -> TTS pipeline end-to-end simulation
def test_capability_25_voice_action_tts_simulation(session):
    mock_tool = MagicMock()
    mock_tool.name = "system"
    mock_tool.can_handle = MagicMock(return_value=True)
    mock_tool.format_result = MagicMock(return_value="Done. Set brightness to 60%.")

    async def _mock_execute(req):
        return ToolResult(
            tool_name="system",
            success=True,
            output={"success": True, "action": "set_brightness", "level": 0.6},
        )

    mock_executor = MagicMock(spec=ToolExecutor)
    mock_executor.execute = AsyncMock(side_effect=_mock_execute)

    mock_registry = MagicMock(spec=ToolRegistry)
    mock_registry.get.return_value = mock_tool

    strategy = PriorityFallbackStrategy(["local"], offline_mode=True)
    router = ModelRouter(providers=[], strategy=strategy, offline_mode=True)

    orchestrator = CompanionOrchestrator(
        router=router,
        tool_registry=mock_registry,
        tool_executor=mock_executor,
        offline_mode=True,
    )

    # Simulate speech transcription
    stt_transcript = "Lyra, decrease the brightness."
    response = asyncio.run(orchestrator.process_turn(session, stt_transcript))

    # Verify action was executed
    assert mock_executor.execute.called
    # Verify concise spoken response suitable for TTS
    assert response == "Done. Set brightness to 60%."
    assert len(response.split()) <= 15
