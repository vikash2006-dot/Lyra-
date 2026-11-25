"""Application service container: one LYRA runtime plus the API services around it."""

from __future__ import annotations

from dataclasses import dataclass, field
import time
from typing import Any, Callable

from lyra.bootstrap import LyraRuntime, build_runtime, build_voice_providers, resolve_data_paths
from lyra.config.settings import load_settings
from lyra.observability.logging import get_logger

from app.core.config import ServerConfig
from app.core.security import RateLimiter
from app.services.chat_service import ChatService
from app.services.document_service import DocumentService
from app.services.events import EventBus, make_event
from app.services.session_service import SessionService
from app.services.store import APIStore
from app.services.task_service import ObservedPlanner, ObservedToolExecutor, TaskTracker
from app.services.voice_service import VoiceService

logger = get_logger("api.container")

RuntimeFactory = Callable[[ServerConfig, Callable[[str, str], None]], LyraRuntime]


def default_runtime_factory(config: ServerConfig, notify: Callable[[str, str], None]) -> LyraRuntime:
    settings = resolve_data_paths(load_settings(), config.data_dir)
    return build_runtime(settings, offline_mode=settings.offline_mode, notification_callback=notify)


@dataclass
class AppServices:
    config: ServerConfig
    runtime: LyraRuntime
    store: APIStore
    bus: EventBus
    sessions: SessionService
    tasks: TaskTracker
    chat: ChatService
    voice: VoiceService
    documents: DocumentService
    limiter: RateLimiter
    started_at: float = field(default_factory=time.time)
    init_errors: list[str] = field(default_factory=list)
    scheduler_running: bool = False

    @property
    def user_id(self) -> str:
        return self.config.user_id


def build_services(config: ServerConfig, runtime_factory: RuntimeFactory | None = None) -> AppServices:
    bus = EventBus()

    def notify(user_id: str, message: str) -> None:
        bus.publish(make_event("notification", level="info", title="Reminder", message=message))

    runtime = (runtime_factory or default_runtime_factory)(config, notify)

    store = APIStore(config.api_db_path)
    interrupted = store.mark_interrupted_tasks()
    if interrupted:
        logger.info("Marked %d tasks from a previous run as interrupted", interrupted)

    tasks = TaskTracker(store, bus)
    # Observe planning and tool execution without changing LYRA's orchestrator logic.
    orch = runtime.orchestrator
    orch.planner = ObservedPlanner(orch.planner, tasks)  # type: ignore[assignment]
    if orch.tool_executor is not None:
        orch.tool_executor = ObservedToolExecutor(orch.tool_executor, tasks)  # type: ignore[assignment]

    sessions = SessionService(store, config.user_id)
    chat = ChatService(orch, sessions, tasks)
    stt, tts = build_voice_providers(runtime.settings)
    voice = VoiceService(runtime.settings, stt, tts)
    documents = DocumentService(
        store=store,
        upload_dir=config.upload_dir,
        max_bytes=config.max_upload_bytes,
        user_id=config.user_id,
        learning=runtime.learning_service,
        chat=chat,
    )
    return AppServices(
        config=config,
        runtime=runtime,
        store=store,
        bus=bus,
        sessions=sessions,
        tasks=tasks,
        chat=chat,
        voice=voice,
        documents=documents,
        limiter=RateLimiter(config.rate_limit_per_minute),
    )


def provider_summaries(runtime: LyraRuntime) -> list[dict[str, Any]]:
    """Provider list that is safe to send to the browser (never includes keys)."""
    from lyra.bootstrap import provider_display_name

    router = runtime.router
    priority = list(runtime.settings.provider_priority)
    out = []
    for p in router.list_providers():
        name = p.name
        rank_key = "ollama" if name == "local" else name
        out.append({
            "name": name,
            "display_name": provider_display_name(name),
            "configured": bool(p.is_configured),
            "status": router.get_provider_status(name).value,
            "model": getattr(p, "_default_model", None),
            "priority": priority.index(rank_key) + 1 if rank_key in priority else None,
            "supports_streaming": bool(p.supports_streaming),
            "supports_vision": bool(p.supports_vision),
            "supports_files": bool(p.supports_files),
        })
    out.sort(key=lambda d: (d["priority"] is None, d["priority"] or 0))
    return out
