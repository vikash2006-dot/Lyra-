"""Fixtures for API tests: a real LYRA runtime with a mock AI provider and temp storage.

Only the AI provider is mocked (no network, no API quota). Planner, tools, memory,
learning, sessions and tasks are the real implementations.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, AsyncIterator

import pytest
from fastapi.testclient import TestClient

from lyra.bootstrap import build_runtime, resolve_data_paths
from lyra.config.settings import load_settings
from lyra.models.messages import AIRequest, AIResponse
from lyra.providers.base import AIProvider
from lyra.tools.filesystem import FilesystemTool

from app.core.config import ServerConfig
from app.main import create_app


class MockProvider(AIProvider):
    """Deterministic stand-in for a cloud LLM (tests only)."""

    def __init__(self, reply: str = "Hello from mock LYRA.", fail: bool = False) -> None:
        self.reply = reply
        self.fail = fail
        self.delay = 0.0
        self.requests: list[AIRequest] = []

    @property
    def name(self) -> str:
        return "mock"

    @property
    def is_configured(self) -> bool:
        return True

    @property
    def supports_streaming(self) -> bool:
        return True

    @property
    def supports_files(self) -> bool:
        return True

    async def generate(self, request: AIRequest) -> AIResponse:
        self.requests.append(request)
        if self.delay:
            import asyncio
            await asyncio.sleep(self.delay * 10)
        if self.fail:
            from lyra.core.exceptions import ProviderResponseError
            raise ProviderResponseError("mock failure")
        return AIResponse(content=self.reply, model="mock-model")

    async def stream(self, request: AIRequest) -> AsyncIterator[str]:
        self.requests.append(request)
        if self.fail:
            from lyra.core.exceptions import ProviderResponseError
            raise ProviderResponseError("mock failure")
        for word in self.reply.split(" "):
            if self.delay:
                import asyncio
                await asyncio.sleep(self.delay)
            yield word + " "


@pytest.fixture
def mock_provider() -> MockProvider:
    return MockProvider()


@pytest.fixture
def home_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    home = tmp_path / "home"
    (home / "Desktop").mkdir(parents=True)
    monkeypatch.setenv("HOME", str(home))
    return home


@pytest.fixture
def server_config(tmp_path: Path) -> ServerConfig:
    storage = tmp_path / "storage"
    return ServerConfig(
        app_env="test",
        storage_dir=storage,
        data_dir=storage / "data",
        upload_dir=storage / "uploads",
        log_dir=storage / "logs",
        max_upload_bytes=1024 * 1024,
        rate_limit_per_minute=0,
        auto_migrate=False,
    )


@pytest.fixture
def client(server_config: ServerConfig, mock_provider: MockProvider, home_dir: Path, monkeypatch) -> TestClient:
    for key in ("GEMINI_API_KEY", "XAI_API_KEY", "GROK_API_KEY", "GROQ_API_KEY", "CEREBRAS_API_KEY",
                "OPENROUTER_API_KEY", "ANAKIN_API_KEY", "ELEVENLABS_API_KEY", "TAVILY_API_KEY"):
        monkeypatch.setenv(key, "")
    monkeypatch.setenv("LOCAL_PROVIDER_ENABLED", "false")
    monkeypatch.setenv("TTS_PROVIDER", "mock")
    monkeypatch.setenv("STT_PROVIDER", "mock")

    def factory(config: ServerConfig, notify: Any):
        settings = resolve_data_paths(load_settings(overrides={"TTS_PROVIDER": "mock", "STT_PROVIDER": "mock"}),
                                      config.data_dir)
        runtime = build_runtime(settings, offline_mode=False, notification_callback=notify,
                                use_mock_computer=True)
        runtime.router._providers.clear()  # no real network providers in tests
        runtime.router.register_provider(mock_provider)
        runtime.tool_registry._tools["filesystem"] = FilesystemTool(default_base_dir=home_dir / "Desktop")
        return runtime

    app = create_app(server_config, runtime_factory=factory, start_scheduler=False)
    with TestClient(app) as c:
        yield c
