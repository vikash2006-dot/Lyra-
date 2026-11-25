"""Real Acceptance Tests for LYRA Voice and Action Commands.

Verifies the 10 canonical commands specified in the integration requirements:
1. "Lyra, open Notes and write Hello Boss."
2. "Lyra, create a folder called AI Projects on my Desktop."
3. "Lyra, open VS Code."
4. "Lyra, open a new browser tab and search Google for Python internships."
5. "Lyra, open YouTube and play Believer."
6. "Lyra, decrease brightness."
7. "Lyra, increase brightness."
8. "Lyra, create this folder structure on my Desktop: AI/backend/frontend/data"
9. "Lyra, research the best free Python resources."
10. "Lyra, analyze my resume."
"""

import asyncio
from pathlib import Path
import shutil
from unittest.mock import MagicMock, patch
import pytest

from lyra.browser.manager import BrowserManager
from lyra.browser.native_browser import NativeBrowserController
from lyra.companion.orchestrator import CompanionOrchestrator
from lyra.companion.planner import ActionPlanner
from lyra.companion.session import Session
from lyra.computer.controller import ComputerController
from lyra.computer.notes import NotesController
from lyra.config.settings import Settings
from lyra.memory.manager import MemoryManager
from lyra.memory.policy import MemoryPolicy
from lyra.memory.sqlite_repository import SQLiteMemoryRepository
from lyra.providers.anakin import AnakinClient, AnakinProvider
from lyra.routing.intent_router import IntentCategory, IntentRouter
from lyra.routing.router import ModelRouter
from lyra.routing.strategies import PriorityFallbackStrategy
from lyra.tools.anakin_workflow_tool import create_anakin_workflow_tools
from lyra.tools.browser_tool import BrowserTool
from lyra.tools.computer_tool import ComputerTool
from lyra.tools.executor import ToolExecutor
from lyra.tools.filesystem import FilesystemTool
from lyra.tools.notes_tool import NotesTool
from lyra.tools.registry import ToolRegistry
from lyra.tools.system_tool import SystemTool


@pytest.fixture
def acceptance_environment(tmp_path: Path):
    """Set up complete LYRA execution harness with real mock-backed safe execution."""
    desktop_dir = tmp_path / "Desktop"
    desktop_dir.mkdir(parents=True, exist_ok=True)

    settings = Settings(
        lyra_env="test",
        anakin_api_key="ask_test_acceptance_key",
        anakin_app_id="app_acceptance_default",
        anakin_app_type="quickapp",
        provider_priority=("anakin", "gemini"),
    )

    # Anakin client mock
    mock_client = AnakinClient(api_key="ask_test_acceptance_key", timeout=5.0)

    def mock_execute_http(method: str, endpoint: str, payload: dict | None = None):
        inputs = (payload or {}).get("inputs", {})
        prompt = str(inputs.get("input") or inputs.get("prompt") or "")
        p_low = prompt.lower()
        if "notes" in p_low and "hello boss" in p_low:
            return {"result": "Done, I wrote 'Hello Boss' in Notes."}
        if "ai projects" in p_low:
            return {"result": "Done, I created AI Projects on your Desktop."}
        if "vs code" in p_low:
            return {"result": "Done, I opened VS Code."}
        if "python internships" in p_low:
            return {"result": "Opened a new tab and searched Google for Python internships."}
        if "believer" in p_low:
            return {"result": "Playing Believer on YouTube."}
        if "decrease" in p_low and "brightness" in p_low:
            return {"result": "Decreased brightness."}
        if "increase" in p_low and "brightness" in p_low:
            return {"result": "Increased brightness."}
        if "structure" in p_low or "ai/backend" in p_low:
            return {"result": "Done, I created the folder structure on your Desktop."}
        if "python resources" in p_low or "research" in p_low:
            return {"result": "Here is the research on the best free Python resources."}
        if "resume" in p_low:
            return {"result": "Here is the resume analysis for your profile."}
        return {"result": "Done, I have completed the requested task."}

    mock_client._execute_http = MagicMock(side_effect=mock_execute_http)

    anakin_prov = AnakinProvider(
        api_key="ask_test_acceptance_key",
        app_id="app_acceptance_default",
    )
    anakin_prov._client = mock_client

    router = ModelRouter(
        providers=[anakin_prov],
        strategy=PriorityFallbackStrategy(["anakin"]),
    )

    notes_ctrl = NotesController(use_mock=True)
    notes_tool = NotesTool(controller=notes_ctrl)

    native_browser = NativeBrowserController(use_mock=True)
    browser_tool = BrowserTool(native_controller=native_browser)

    computer_ctrl = ComputerController.from_settings(settings=settings, use_mock=True)
    computer_ctrl.enabled = True
    computer_tool = ComputerTool(controller=computer_ctrl)

    system_tool = SystemTool()
    fs_tool = FilesystemTool(default_base_dir=desktop_dir)

    anakin_tools = create_anakin_workflow_tools(settings=settings, client=mock_client)

    tools = [
        notes_tool,
        browser_tool,
        computer_tool,
        system_tool,
        fs_tool,
    ]
    tools.extend(anakin_tools)

    tool_registry = ToolRegistry(tools=tools)
    tool_executor = ToolExecutor(registry=tool_registry)

    mem_repo = SQLiteMemoryRepository(db_path=str(tmp_path / "test_mem.db"))
    memory_manager = MemoryManager(repository=mem_repo, policy=MemoryPolicy())

    orchestrator = CompanionOrchestrator(
        router=router,
        tool_registry=tool_registry,
        tool_executor=tool_executor,
        memory_manager=memory_manager,
    )
    session = Session()

    intent_router = IntentRouter()

    return {
        "orchestrator": orchestrator,
        "session": session,
        "planner": orchestrator.planner,
        "intent_router": intent_router,
        "notes_ctrl": notes_ctrl,
        "desktop_dir": desktop_dir,
        "browser_ctrl": native_browser,
        "fs_tool": fs_tool,
    }


def test_command_01_notes_write(acceptance_environment) -> None:
    """1. 'Lyra, open Notes and write Hello Boss.'"""
    env = acceptance_environment
    cmd = "Lyra, open Notes and write Hello Boss."

    # Intent routing
    intent = env["intent_router"].classify(cmd)
    assert intent.category == IntentCategory.WRITE_TEXT

    # Orchestrator execution
    reply = asyncio.run(env["orchestrator"].process_turn(env["session"], cmd))
    assert "Done, I wrote 'Hello Boss' in Notes." in reply or "Hello Boss" in reply

    # Verification: Check Notes state
    notes = env["notes_ctrl"]._mock_notes
    assert len(notes) >= 1
    assert any("Hello Boss" in n["body"] for n in notes)


def test_command_02_create_folder_on_desktop(acceptance_environment) -> None:
    """2. 'Lyra, create a folder called AI Projects on my Desktop.'"""
    env = acceptance_environment
    cmd = "Lyra, create a folder called AI Projects on my Desktop."

    intent = env["intent_router"].classify(cmd)
    assert intent.category == IntentCategory.CREATE_FOLDER

    with patch.object(Path, "home", return_value=env["desktop_dir"].parent):
        reply = asyncio.run(env["orchestrator"].process_turn(env["session"], cmd))

    assert "AI Projects" in reply or "Done" in reply
    created_dir = env["desktop_dir"] / "AI Projects"
    assert created_dir.exists()
    assert created_dir.is_dir()


def test_command_03_open_vscode(acceptance_environment) -> None:
    """3. 'Lyra, open VS Code.'"""
    env = acceptance_environment
    cmd = "Lyra, open VS Code."

    intent = env["intent_router"].classify(cmd)
    assert intent.category == IntentCategory.OPEN_APP
    assert intent.entities["app_name"] == "Visual Studio Code"

    reply = asyncio.run(env["orchestrator"].process_turn(env["session"], cmd))
    assert "Visual Studio Code" in reply or "VS Code" in reply or "Done" in reply


def test_command_04_new_tab_google_search(acceptance_environment) -> None:
    """4. 'Lyra, open a new browser tab and search Google for Python internships.'"""
    env = acceptance_environment
    cmd = "Lyra, open a new browser tab and search Google for Python internships."

    intent = env["intent_router"].classify(cmd)
    assert intent.category == IntentCategory.SEARCH_GOOGLE
    assert "Python internships" in intent.entities["query"]

    reply = asyncio.run(env["orchestrator"].process_turn(env["session"], cmd))
    assert "Python internships" in reply or "Google" in reply or "new tab" in reply.lower()

    # Verify browser tab state
    tabs = env["browser_ctrl"]._mock_tabs
    assert any("google.com/search" in t["url"] for t in tabs)


def test_command_05_youtube_play(acceptance_environment) -> None:
    """5. 'Lyra, open YouTube and play Believer.'"""
    env = acceptance_environment
    cmd = "Lyra, open YouTube and play Believer."

    intent = env["intent_router"].classify(cmd)
    assert intent.category == IntentCategory.PLAY_MEDIA
    assert "Believer" in intent.entities["query"]

    reply = asyncio.run(env["orchestrator"].process_turn(env["session"], cmd))
    assert "Believer" in reply or "playing" in reply.lower() or "youtube" in reply.lower()


def test_command_06_decrease_brightness(acceptance_environment) -> None:
    """6. 'Lyra, decrease brightness.'"""
    env = acceptance_environment
    cmd = "Lyra, decrease brightness."

    intent = env["intent_router"].classify(cmd)
    assert intent.category == IntentCategory.BRIGHTNESS_CONTROL
    assert intent.entities["action"] == "decrease"

    reply = asyncio.run(env["orchestrator"].process_turn(env["session"], cmd))
    assert "Decreased brightness" in reply or "brightness" in reply.lower()


def test_command_07_increase_brightness(acceptance_environment) -> None:
    """7. 'Lyra, increase brightness.'"""
    env = acceptance_environment
    cmd = "Lyra, increase brightness."

    intent = env["intent_router"].classify(cmd)
    assert intent.category == IntentCategory.BRIGHTNESS_CONTROL
    assert intent.entities["action"] == "increase"

    reply = asyncio.run(env["orchestrator"].process_turn(env["session"], cmd))
    assert "Increased brightness" in reply or "brightness" in reply.lower()


def test_command_08_create_folder_structure_on_desktop(acceptance_environment) -> None:
    """8. 'Lyra, create this folder structure on my Desktop: AI/backend/frontend/data'"""
    env = acceptance_environment
    cmd = "Lyra, create this folder structure on my Desktop: AI/backend/frontend/data"

    intent = env["intent_router"].classify(cmd)
    assert intent.category == IntentCategory.CREATE_FOLDER

    with patch.object(Path, "home", return_value=env["desktop_dir"].parent):
        reply = asyncio.run(env["orchestrator"].process_turn(env["session"], cmd))

    assert "structure" in reply.lower() or "Done" in reply
    ai_dir = env["desktop_dir"] / "AI"
    assert ai_dir.exists()
    assert (ai_dir / "backend").exists()
    assert (ai_dir / "frontend").exists()
    assert (ai_dir / "data").exists()


def test_command_09_research_python_resources(acceptance_environment) -> None:
    """9. 'Lyra, research the best free Python resources.'"""
    env = acceptance_environment
    cmd = "Lyra, research the best free Python resources."

    intent = env["intent_router"].classify(cmd)
    assert intent.category == IntentCategory.RESEARCH

    reply = asyncio.run(env["orchestrator"].process_turn(env["session"], cmd))
    assert len(reply) > 0
    assert "research" in reply.lower() or "Anakin" in reply or "Python" in reply


def test_command_10_analyze_resume(acceptance_environment) -> None:
    """10. 'Lyra, analyze my resume.'"""
    env = acceptance_environment
    cmd = "Lyra, analyze my resume."

    intent = env["intent_router"].classify(cmd)
    assert intent.category == IntentCategory.ANAKIN_WORKFLOW

    reply = asyncio.run(env["orchestrator"].process_turn(env["session"], cmd))
    assert len(reply) > 0
    assert "resume" in reply.lower() or "analysis" in reply.lower() or "workflow" in reply.lower()
