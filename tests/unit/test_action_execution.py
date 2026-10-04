"""Integration and end-to-end tests for Action-Executing Personal Assistant pipeline.

Verifies the complete UNDERSTANDS -> PLANS -> EXECUTES -> VERIFIES -> RESPONDS workflow
across the 6 user-specified success criteria:
1. Create folder on desktop
2. Open Google and search
3. Open YouTube and play media
4. Open application (Finder)
5. Multi-step: Create folder and file inside it
6. Delete folder with confirmation
"""

import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch
import pytest

from lyra.browser.manager import BrowserManager
from lyra.browser.mock_driver import MockBrowserDriver
from lyra.companion.orchestrator import CompanionOrchestrator
from lyra.companion.session import Session
from lyra.computer.controller import ComputerController
from lyra.computer.mock import MockApplicationController
from lyra.computer.policy import ComputerPolicy
from lyra.routing.router import ModelRouter
from lyra.routing.strategies import PriorityFallbackStrategy
from lyra.tools.browser_tool import BrowserTool
from lyra.tools.computer_tool import ComputerTool
from lyra.tools.executor import ToolExecutor
from lyra.tools.filesystem import FilesystemTool
from lyra.tools.registry import ToolRegistry


@pytest.fixture
def test_environment(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Sets up an isolated, sandboxed environment for testing action execution."""
    # Redirect HOME to isolated tmp_path so ~/Desktop operations don't touch real user Desktop
    monkeypatch.setenv("HOME", str(tmp_path))
    desktop_dir = tmp_path / "Desktop"
    desktop_dir.mkdir(parents=True, exist_ok=True)

    # Browser subsystem
    mock_browser_driver = MockBrowserDriver()
    browser_manager = BrowserManager(driver=mock_browser_driver)
    browser_tool = BrowserTool(manager=browser_manager)

    # Computer subsystem
    mock_app_controller = MockApplicationController()
    computer_controller = ComputerController(
        applications=mock_app_controller,
        policy=ComputerPolicy(),
        enabled=True,
    )
    computer_tool = ComputerTool(controller=computer_controller)

    # Filesystem subsystem
    filesystem_tool = FilesystemTool(default_base_dir=desktop_dir)

    # Tool registry and executor
    tools = [filesystem_tool, browser_tool, computer_tool]
    registry = ToolRegistry(tools=tools)
    executor = ToolExecutor(registry=registry)

    # Router without external API keys (testing truthful deterministic execution responses)
    strategy = PriorityFallbackStrategy(["local"], offline_mode=True)
    router = ModelRouter(providers=[], strategy=strategy, offline_mode=True)

    # Companion Orchestrator
    orchestrator = CompanionOrchestrator(
        router=router,
        tool_registry=registry,
        tool_executor=executor,
        offline_mode=True,
    )

    return {
        "tmp_path": tmp_path,
        "desktop_dir": desktop_dir,
        "orchestrator": orchestrator,
        "mock_browser_driver": mock_browser_driver,
        "mock_app_controller": mock_app_controller,
    }


def test_scenario_1_create_folder_on_desktop(test_environment):
    """TEST 1: User says: 'Lyra, create a folder on my desktop named TestFolder.'

    Expected: ~/Desktop/TestFolder actually exists.
    LYRA says: 'Done, I created TestFolder on your Desktop.'
    """
    async def _test():
        orchestrator = test_environment["orchestrator"]
        desktop_dir = test_environment["desktop_dir"]
        session = Session()

        response = await orchestrator.process_turn(session, "Lyra, create a folder on my desktop named TestFolder.")

        expected_folder = desktop_dir / "TestFolder"
        assert expected_folder.exists()
        assert expected_folder.is_dir()
        assert "Done, I created TestFolder on your Desktop" in response

    asyncio.run(_test())


def test_scenario_2_open_google_and_search(test_environment):
    """TEST 2: User says: 'Lyra, open Google and search for Python tutorials.'

    Expected: Browser actually opens Google and performs the search.
    """
    async def _test():
        orchestrator = test_environment["orchestrator"]
        mock_driver = test_environment["mock_browser_driver"]
        session = Session()

        response = await orchestrator.process_turn(session, "Lyra, open Google and search for Python tutorials.")

        # Verify Google search was navigated to in the browser session
        assert "google.com/search" in mock_driver.current_url
        assert "Python+tutorials" in mock_driver.current_url or "Python%20tutorials" in mock_driver.current_url
        assert "Searched Google for 'Python tutorials'" in response or "Opened Google" in response

    asyncio.run(_test())


def test_scenario_3_open_youtube_and_play(test_environment):
    """TEST 3: User says: 'Lyra, open YouTube and play Believer.'

    Expected: Browser opens YouTube, searches for Believer and attempts to play result.
    """
    async def _test():
        orchestrator = test_environment["orchestrator"]
        mock_driver = test_environment["mock_browser_driver"]
        session = Session()

        response = await orchestrator.process_turn(session, "Lyra, open YouTube and play Believer.")

        # Verify browser navigated to YouTube search
        assert "youtube.com" in mock_driver.current_url
        assert "Believer" in mock_driver.current_url
        assert "Believer" in response

    asyncio.run(_test())


def test_scenario_4_open_application_finder(test_environment):
    """TEST 4: User says: 'Lyra, open Finder.'

    Expected: Finder actually launches.
    """
    async def _test():
        orchestrator = test_environment["orchestrator"]
        app_controller = test_environment["mock_app_controller"]
        session = Session()

        response = await orchestrator.process_turn(session, "Lyra, open Finder.")

        assert "Finder" in app_controller.launched_apps
        assert "Finder" in response

    asyncio.run(_test())


def test_scenario_5_multi_step_create_folder_and_file(test_environment):
    """TEST 5: User says: 'Lyra, create a folder called Projects on my desktop and create a file called todo.txt inside it.'

    Expected: Both operations actually happen on disk.
    """
    async def _test():
        orchestrator = test_environment["orchestrator"]
        desktop_dir = test_environment["desktop_dir"]
        session = Session()

        prompt = "Lyra, create a folder called Projects on my desktop and create a file called todo.txt inside it."
        response = await orchestrator.process_turn(session, prompt)

        expected_folder = desktop_dir / "Projects"
        expected_file = expected_folder / "todo.txt"

        assert expected_folder.exists() and expected_folder.is_dir()
        assert expected_file.exists() and expected_file.is_file()
        assert "Projects" in response
        assert "todo.txt" in response

    asyncio.run(_test())


def test_scenario_6_delete_confirmation_flow(test_environment):
    """TEST 6: User says: 'Lyra, delete the Projects folder.'

    Expected: LYRA asks for confirmation before deletion, and deletes only upon confirmation.
    """
    async def _test():
        orchestrator = test_environment["orchestrator"]
        desktop_dir = test_environment["desktop_dir"]
        session = Session()

        # Pre-create the Projects folder
        projects_folder = desktop_dir / "Projects"
        projects_folder.mkdir(parents=True, exist_ok=True)
        assert projects_folder.exists()

        # 1. First turn: user asks to delete
        response1 = await orchestrator.process_turn(session, "Lyra, delete the Projects folder.")
        assert "destructive action" in response1 or "confirmation" in response1.lower()
        assert projects_folder.exists()  # Not yet deleted!

        # 2. Second turn: user confirms with "yes"
        response2 = await orchestrator.process_turn(session, "Yes, confirm.")
        assert "deleted" in response2.lower()
        assert not projects_folder.exists()  # Now actually deleted!

    asyncio.run(_test())


def test_truthful_failure_handling(test_environment, monkeypatch: pytest.MonkeyPatch):
    """Verify that if a tool execution fails, LYRA never claims success and truthfully reports error."""
    async def _test():
        orchestrator = test_environment["orchestrator"]
        session = Session()

        # Simulate permission error by mocking tool executor to fail
        async def mock_fail_execute(req):
            from lyra.models.tools import ToolResult
            return ToolResult(
                tool_name=req.tool_name,
                success=False,
                error="macOS denied access to the Desktop (Permission denied)",
            )

        monkeypatch.setattr(orchestrator.tool_executor, "execute", mock_fail_execute)

        response = await orchestrator.process_turn(session, "Lyra, create a folder on my desktop named ProtectedFolder.")

        assert "couldn't" in response or "denied" in response or "Permission denied" in response
        assert "Done, I created" not in response  # Must NOT pretend it succeeded!

    asyncio.run(_test())


def test_voice_conversation_turn_integration(test_environment):
    """Verify that continuous voice conversation loop executes action commands and speaks results."""
    async def _test():
        from lyra.voice.conversation import VoiceConversationManager
        from lyra.voice.providers.mock import MockSTTProvider, MockTTSProvider
        from lyra.voice.player import AudioPlayer
        from lyra.config.settings import load_settings

        orchestrator = test_environment["orchestrator"]
        desktop_dir = test_environment["desktop_dir"]
        session = Session()
        settings = load_settings()

        stt = MockSTTProvider()
        tts = MockTTSProvider()
        player = AudioPlayer()

        manager = VoiceConversationManager(
            orchestrator=orchestrator,
            session=session,
            capture=MagicMock(),
            stt_provider=stt,
            tts_provider=tts,
            player=player,
            settings=settings,
        )

        # Mock capture turn to return speech bytes for action command
        manager.capture.capture_turn = AsyncMock(return_value=b"DUMMY_AUDIO_BYTES")
        stt.set_transcription_text("Lyra, create a folder on my desktop named VoiceFolder")

        should_continue = await manager.process_one_turn()

        assert should_continue is True  # Continuous voice mode remains active!
        expected_folder = desktop_dir / "VoiceFolder"
        assert expected_folder.exists()
        assert expected_folder.is_dir()

    asyncio.run(_test())
