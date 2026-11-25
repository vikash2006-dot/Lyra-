"""Shared runtime wiring for LYRA.

Builds the provider pool, model router, memory, learning, tools, automation, auth and
companion orchestrator exactly once, so every interface (CLI, voice loop, HTTP API)
runs the same LYRA core instead of duplicating construction logic.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
import os
from pathlib import Path
import sys
from typing import Any, Callable

from lyra.auth.local import LocalAuthProvider
from lyra.auth.manager import AuthManager
from lyra.automation.executor import AutomationExecutor
from lyra.automation.scheduler import Scheduler
from lyra.automation.sqlite_store import SQLiteAutomationStore
from lyra.browser.manager import BrowserManager
from lyra.companion.orchestrator import CompanionOrchestrator
from lyra.computer.controller import ComputerController
from lyra.config.settings import Settings
from lyra.learning.repository import SQLiteLearningRepository
from lyra.learning.service import LearningService
from lyra.memory.manager import MemoryManager
from lyra.memory.policy import MemoryPolicy
from lyra.memory.sqlite_repository import SQLiteMemoryRepository
from lyra.providers.anakin import AnakinProvider
from lyra.providers.cerebras import CerebrasProvider
from lyra.providers.gemini import GeminiProvider
from lyra.providers.groq import GroqProvider
from lyra.providers.local import LocalProvider, LocalProviderConfig
from lyra.providers.openrouter import OpenRouterProvider
from lyra.providers.xai import XAIProvider
from lyra.routing.router import ModelRouter
from lyra.routing.strategies import PriorityFallbackStrategy
from lyra.tools.anakin_workflow_tool import create_anakin_workflow_tools
from lyra.tools.browser_tool import BrowserTool
from lyra.tools.computer_tool import ComputerTool
from lyra.tools.executor import ToolExecutor
from lyra.tools.file_tool import FileTool
from lyra.tools.filesystem import FilesystemTool
from lyra.tools.keyboard_mouse_tool import KeyboardTool, MouseTool
from lyra.tools.learning_tools import create_learning_tools
from lyra.tools.maps import MapsTool
from lyra.tools.media_tool import MediaTool
from lyra.tools.memory_tool import MemoryTool
from lyra.tools.news import NewsTool
from lyra.tools.notes_tool import NotesTool
from lyra.tools.registry import ToolRegistry
from lyra.tools.search import SearchTool
from lyra.tools.system_tool import SystemTool
from lyra.tools.time_tool import TimeTool
from lyra.tools.vision_tool import VisionTool
from lyra.tools.weather import WeatherTool

DATA_DIR_ENV = "LYRA_DATA_DIR"

PROVIDER_DISPLAY_NAMES: dict[str, str] = {
    "gemini": "Gemini",
    "xai": "Grok",
    "groq": "Groq",
    "cerebras": "Cerebras",
    "openrouter": "OpenRouter",
    "anakin": "Anakin",
    "local": "Ollama",
}


def provider_display_name(name: str) -> str:
    return PROVIDER_DISPLAY_NAMES.get(name, name.capitalize())


def resolve_data_paths(settings: Settings, data_dir: str | Path | None = None) -> Settings:
    """Anchor relative database/storage paths to the LYRA data directory.

    When ``data_dir`` is not given, the ``LYRA_DATA_DIR`` environment variable is used.
    If neither is set, settings are returned untouched (legacy CWD-relative behaviour).
    Absolute paths configured by the user are always respected.
    """
    target = data_dir or os.environ.get(DATA_DIR_ENV)
    if not target:
        return settings
    base = Path(target).expanduser().resolve()
    base.mkdir(parents=True, exist_ok=True)

    def _anchor(value: str) -> str:
        p = Path(value).expanduser()
        return str(p if p.is_absolute() else base / p)

    return replace(
        settings,
        memory_db_path=_anchor(settings.memory_db_path),
        auth_db_path=_anchor(settings.auth_db_path),
        automation_db_path=_anchor(settings.automation_db_path),
        learning_db_path=_anchor(settings.learning_db_path),
        browser_download_dir=_anchor(settings.browser_download_dir),
        computer_screenshot_dir=_anchor(settings.computer_screenshot_dir),
    )


def build_providers(settings: Settings) -> list[Any]:
    """Construct the full AI provider pool (order does not imply priority)."""
    local_provider = LocalProvider(config=LocalProviderConfig.from_settings(settings))
    gemini_provider = GeminiProvider(
        api_key=settings.gemini_api_key,
        default_model=settings.gemini_model,
        timeout=settings.request_timeout_seconds,
        base_url=settings.gemini_base_url,
    )
    xai_provider = XAIProvider(
        api_key=settings.xai_api_key,
        default_model=settings.xai_model,
        timeout=settings.request_timeout_seconds,
    )
    return [
        gemini_provider,
        xai_provider,
        GroqProvider(),
        CerebrasProvider(),
        OpenRouterProvider(),
        AnakinProvider(),
        local_provider,
    ]


def build_router(settings: Settings, offline_mode: bool) -> ModelRouter:
    strategy = PriorityFallbackStrategy(settings.provider_priority, offline_mode=offline_mode)
    return ModelRouter(providers=build_providers(settings), strategy=strategy, offline_mode=offline_mode)


def build_voice_providers(settings: Settings) -> tuple[Any, Any]:
    """Return (stt_provider, tts_provider) according to configuration."""
    from lyra.voice.providers.elevenlabs import ElevenLabsTTSProvider
    from lyra.voice.providers.free_stt import FreeSTTProvider
    from lyra.voice.providers.mock import MockSTTProvider, MockTTSProvider
    from lyra.voice.providers.system import SystemTTSProvider

    stt: Any = MockSTTProvider() if settings.stt_provider == "mock" else FreeSTTProvider()
    if settings.tts_provider == "mock":
        tts: Any = MockTTSProvider()
    elif settings.tts_provider == "elevenlabs" and settings.elevenlabs_api_key:
        tts = ElevenLabsTTSProvider(
            api_key=settings.elevenlabs_api_key,
            default_voice_id=settings.elevenlabs_voice_id,
        )
    else:
        tts = SystemTTSProvider()
    return stt, tts


@dataclass
class LyraRuntime:
    """Fully wired LYRA core services."""

    settings: Settings
    offline_mode: bool
    router: ModelRouter
    memory_manager: MemoryManager
    learning_service: LearningService
    tool_registry: ToolRegistry
    tool_executor: ToolExecutor
    browser_manager: BrowserManager
    computer_controller: ComputerController
    automation_store: SQLiteAutomationStore
    scheduler: Scheduler
    auth_manager: AuthManager
    orchestrator: CompanionOrchestrator


def build_runtime(
    settings: Settings,
    offline_mode: bool = False,
    notification_callback: Callable[[str, str], None] | None = None,
    use_mock_computer: bool | None = None,
) -> LyraRuntime:
    """Wire every LYRA subsystem together and return the runtime container."""
    router = build_router(settings, offline_mode)

    # Memory
    memory_repo = SQLiteMemoryRepository(db_path=settings.memory_db_path)
    memory_manager = MemoryManager(repository=memory_repo, policy=MemoryPolicy())

    # Browser + computer control
    browser_manager = BrowserManager(settings=settings)
    if use_mock_computer is None:
        use_mock_computer = "pytest" in sys.modules or sys.platform != "darwin"
    computer_controller = ComputerController.from_settings(settings=settings, use_mock=use_mock_computer)
    computer_controller.enabled = True

    # Adaptive learning
    learning_repo = SQLiteLearningRepository(db_path=settings.learning_db_path)
    learning_service = LearningService(
        repository=learning_repo,
        router=router,
        memory_manager=memory_manager,
        db_path=settings.learning_db_path,
    )

    tools: list[Any] = [
        TimeTool(),
        WeatherTool(),
        SearchTool(),
        NewsTool(),
        MapsTool(),
        MemoryTool(memory_manager=memory_manager),
        FileTool(),
        FilesystemTool(),
        VisionTool(),
        BrowserTool(manager=browser_manager),
        ComputerTool(controller=computer_controller),
        SystemTool(),
        NotesTool(),
        MediaTool(),
        KeyboardTool(),
        MouseTool(),
    ]
    tools.extend(create_learning_tools(learning_service))
    tools.extend(create_anakin_workflow_tools(settings=settings))
    tool_registry = ToolRegistry(tools=tools)
    learning_service.tool_registry = tool_registry
    tool_executor = ToolExecutor(registry=tool_registry, offline_mode=offline_mode)

    # Automation
    automation_store = SQLiteAutomationStore(db_path=settings.automation_db_path)
    automation_executor = AutomationExecutor(
        store=automation_store,
        tool_executor=tool_executor,
        notification_callback=notification_callback
        or (lambda uid, msg: sys.stdout.write(f"\n[REMINDER: {msg}]\n")),
    )
    scheduler = Scheduler(
        store=automation_store,
        executor=automation_executor,
        poll_interval_seconds=settings.automation_poll_interval_seconds,
    )

    # Auth
    auth_provider = LocalAuthProvider(
        db_path=settings.auth_db_path,
        token_ttl_seconds=settings.auth_token_ttl_seconds,
        max_failed_attempts=settings.auth_max_failed_attempts,
        lockout_duration_seconds=settings.auth_lockout_duration_seconds,
    )
    auth_manager = AuthManager(
        provider=auth_provider,
        memory_manager=memory_manager,
        scheduler=scheduler,
    )

    orchestrator = CompanionOrchestrator(
        router=router,
        tool_registry=tool_registry,
        tool_executor=tool_executor,
        memory_manager=memory_manager,
        offline_mode=offline_mode,
        learning_service=learning_service,
    )

    return LyraRuntime(
        settings=settings,
        offline_mode=offline_mode,
        router=router,
        memory_manager=memory_manager,
        learning_service=learning_service,
        tool_registry=tool_registry,
        tool_executor=tool_executor,
        browser_manager=browser_manager,
        computer_controller=computer_controller,
        automation_store=automation_store,
        scheduler=scheduler,
        auth_manager=auth_manager,
        orchestrator=orchestrator,
    )
