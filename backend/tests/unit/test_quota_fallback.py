"""Unit and integration tests for Gemini 429 quota exhaustion, health tracking, and automated fallback.

Verifies:
1. Gemini success as primary provider
2. Gemini 429 triggers automated fallback to Groq
3. Gemini quota exhausted state skips Gemini during active cooldown
4. Cooldown expiration restores Gemini to AVAILABLE
5. All providers unavailable raises friendly error without leaking secrets
6. Tool execution (create folder on desktop) works after fallback
7. Voice conversation turn continues smoothly after fallback
8. No API keys exposed in logs or errors
"""

import asyncio
from pathlib import Path
import time
from typing import AsyncIterator
from unittest.mock import AsyncMock, MagicMock, patch
import pytest

from lyra.companion.orchestrator import CompanionOrchestrator
from lyra.companion.session import Session
from lyra.core.exceptions import (
    NoAvailableProviderError,
    ProviderError,
    ProviderQuotaExceededError,
    ProviderRateLimitError,
)
from lyra.models.messages import AIRequest, AIResponse, Message, Role
from lyra.observability.logging import sanitize_text
from lyra.providers.base import AIProvider
from lyra.routing.health import ProviderHealthStatus, ProviderHealthTracker
from lyra.routing.router import ModelRouter
from lyra.routing.strategies import PriorityFallbackStrategy
from lyra.tools.executor import ToolExecutor
from lyra.tools.filesystem import FilesystemTool
from lyra.tools.registry import ToolRegistry


class MockStreamingProvider(AIProvider):
    """Mock AIProvider for testing text generation and streaming fallback."""

    def __init__(
        self,
        name: str,
        is_configured: bool = True,
        fail_with: Exception | None = None,
        return_content: str | None = None,
    ) -> None:
        self._name = name
        self._is_configured = is_configured
        self._fail_with = fail_with
        self._return_content = return_content or f"Response from {name}"
        self.call_count = 0
        self.stream_call_count = 0

    @property
    def name(self) -> str:
        return self._name

    @property
    def is_configured(self) -> bool:
        return self._is_configured

    @property
    def supports_streaming(self) -> bool:
        return True

    async def generate(self, request: AIRequest) -> AIResponse:
        self.call_count += 1
        if self._fail_with:
            raise self._fail_with
        return AIResponse(
            content=self._return_content,
            model=f"{self._name}-test-model",
            role=Role.ASSISTANT,
            metadata={"provider": self._name},
        )

    async def stream(self, request: AIRequest) -> AsyncIterator[str]:
        self.stream_call_count += 1
        if self._fail_with:
            raise self._fail_with
        tokens = self._return_content.split(" ")
        for i, token in enumerate(tokens):
            yield token if i == 0 else f" {token}"


@pytest.fixture
def sample_request() -> AIRequest:
    return AIRequest(
        messages=[Message(role=Role.USER, content="Hello LYRA")],
    )


def test_gemini_success(sample_request: AIRequest):
    """1. Gemini success: Gemini is primary and fulfills request when healthy."""
    gemini = MockStreamingProvider("gemini", return_content="Hello from Gemini!")
    groq = MockStreamingProvider("groq", return_content="Hello from Groq!")

    tracker = ProviderHealthTracker()
    strategy = PriorityFallbackStrategy(["gemini", "groq"])
    router = ModelRouter(providers=[gemini, groq], strategy=strategy, tracker=tracker)

    response = asyncio.run(router.route(sample_request))

    assert response.content == "Hello from Gemini!"
    assert gemini.call_count == 1
    assert groq.call_count == 0
    assert tracker.get_status(gemini) == ProviderHealthStatus.AVAILABLE


def test_gemini_429_triggers_fallback(sample_request: AIRequest):
    """2. Gemini 429: Gemini returns 429 RESOURCE_EXHAUSTED, automatically switches to Groq."""
    gemini_429_err = ProviderQuotaExceededError(
        "Gemini quota exhausted (HTTP 429): Resource has been exhausted (e.g. check quota)."
    )
    gemini = MockStreamingProvider("gemini", fail_with=gemini_429_err)
    groq = MockStreamingProvider("groq", return_content="Hello from fallback Groq!")

    tracker = ProviderHealthTracker(default_cooldown_seconds=60.0)
    strategy = PriorityFallbackStrategy(["gemini", "groq"])
    router = ModelRouter(providers=[gemini, groq], strategy=strategy, tracker=tracker)

    response = asyncio.run(router.route(sample_request))

    # Gemini failed with 429, Groq took over seamlessly
    assert response.content == "Hello from fallback Groq!"
    assert gemini.call_count == 1
    assert groq.call_count == 1
    assert tracker.get_status(gemini) == ProviderHealthStatus.QUOTA_EXHAUSTED
    assert tracker.get_status(groq) == ProviderHealthStatus.AVAILABLE


def test_gemini_quota_exhausted_skips_gemini(sample_request: AIRequest):
    """3. Gemini quota exhausted: Skips Gemini without retrying while in active cooldown."""
    gemini_429_err = ProviderQuotaExceededError("Gemini quota exhausted (HTTP 429)")
    gemini = MockStreamingProvider("gemini", fail_with=gemini_429_err)
    groq = MockStreamingProvider("groq", return_content="Groq response")

    tracker = ProviderHealthTracker(default_cooldown_seconds=60.0)
    strategy = PriorityFallbackStrategy(["gemini", "groq"])
    router = ModelRouter(providers=[gemini, groq], strategy=strategy, tracker=tracker)

    # First turn exhausts Gemini quota
    resp1 = asyncio.run(router.route(sample_request))
    assert resp1.content == "Groq response"
    assert gemini.call_count == 1
    assert groq.call_count == 1

    # Second turn during cooldown window: Gemini MUST be skipped immediately
    resp2 = asyncio.run(router.route(sample_request))
    assert resp2.content == "Groq response"
    assert gemini.call_count == 1  # Did NOT retry Gemini!
    assert groq.call_count == 2   # Groq answered directly


def test_cooldown_expiration_restores_gemini(sample_request: AIRequest, monkeypatch: pytest.MonkeyPatch):
    """4. Cooldown expiration: Restores Gemini to AVAILABLE when quota resets."""
    gemini_429_err = ProviderQuotaExceededError("Gemini 429")
    gemini = MockStreamingProvider("gemini", fail_with=gemini_429_err)
    groq = MockStreamingProvider("groq", return_content="Groq response")

    tracker = ProviderHealthTracker(default_cooldown_seconds=30.0)
    strategy = PriorityFallbackStrategy(["gemini", "groq"])
    router = ModelRouter(providers=[gemini, groq], strategy=strategy, tracker=tracker)

    # Trigger quota exhaustion
    asyncio.run(router.route(sample_request))
    assert tracker.get_status(gemini) == ProviderHealthStatus.QUOTA_EXHAUSTED

    # Fast forward time past the 30-second cooldown
    future_time = time.monotonic() + 35.0
    monkeypatch.setattr(time, "monotonic", lambda: future_time)

    # Gemini should now be restored to AVAILABLE
    assert tracker.get_status(gemini) == ProviderHealthStatus.AVAILABLE

    # Reset Gemini to succeed on next call
    gemini._fail_with = None
    gemini._return_content = "Gemini recovered!"

    resp = asyncio.run(router.route(sample_request))
    assert resp.content == "Gemini recovered!"
    assert gemini.call_count == 2


def test_all_providers_unavailable(sample_request: AIRequest):
    """5. All providers unavailable: Raises NoAvailableProviderError, handled cleanly by companion."""
    gemini = MockStreamingProvider("gemini", fail_with=ProviderQuotaExceededError("Gemini exhausted"))
    groq = MockStreamingProvider("groq", fail_with=ProviderError("Groq server error"))

    tracker = ProviderHealthTracker()
    strategy = PriorityFallbackStrategy(["gemini", "groq"])
    router = ModelRouter(providers=[gemini, groq], strategy=strategy, tracker=tracker)

    session = Session()
    orchestrator = CompanionOrchestrator(router=router)

    # Companion handles all providers failing gracefully without crashing or showing raw tracebacks
    reply = asyncio.run(orchestrator.process_turn(session, "Hello LYRA"))
    assert "unavailable" in reply.lower() or "quota" in reply.lower()
    assert "Traceback" not in reply
    assert "key=" not in reply


def test_tool_execution_after_fallback(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """6. Tool execution after fallback: Action executes on disk and response is synthesized via fallback provider."""
    monkeypatch.setenv("HOME", str(tmp_path))
    desktop_dir = tmp_path / "Desktop"
    desktop_dir.mkdir(parents=True, exist_ok=True)

    # Gemini is exhausted; Groq is healthy and ready to synthesize action results
    gemini = MockStreamingProvider(
        "gemini",
        fail_with=ProviderQuotaExceededError("Gemini 429 RESOURCE_EXHAUSTED free tier exceeded"),
    )
    groq = MockStreamingProvider(
        "groq",
        return_content="Done, I created the Projects folder on your Desktop.",
    )

    tracker = ProviderHealthTracker()
    strategy = PriorityFallbackStrategy(["gemini", "groq"])
    router = ModelRouter(providers=[gemini, groq], strategy=strategy, tracker=tracker)

    filesystem_tool = FilesystemTool(default_base_dir=desktop_dir)
    registry = ToolRegistry(tools=[filesystem_tool])
    executor = ToolExecutor(registry=registry)

    orchestrator = CompanionOrchestrator(
        router=router,
        tool_registry=registry,
        tool_executor=executor,
    )
    session = Session()

    reply = asyncio.run(orchestrator.process_turn(session, "Lyra, create a folder named Projects on my desktop."))

    # 1. Action executed in reality on the filesystem
    expected_folder = desktop_dir / "Projects"
    assert expected_folder.exists()
    assert expected_folder.is_dir()

    # 2. Gemini was attempted and marked exhausted
    assert tracker.get_status(gemini) == ProviderHealthStatus.QUOTA_EXHAUSTED

    # 3. Groq synthesized the confirmation response
    assert "Projects" in reply
    assert groq.call_count >= 1


def test_voice_conversation_after_fallback():
    """7. Voice conversation after fallback: Voice stream continues smoothly using fallback provider."""
    from lyra.voice.conversation import VoiceConversationManager
    from lyra.voice.providers.mock import MockSTTProvider, MockTTSProvider
    from lyra.voice.player import AudioPlayer
    from lyra.config.settings import load_settings

    # Gemini stream fails with 429; Groq stream succeeds
    gemini = MockStreamingProvider(
        "gemini",
        fail_with=ProviderQuotaExceededError("Gemini 429 stream quota exhausted"),
    )
    groq = MockStreamingProvider(
        "groq",
        return_content="Certainly! I am here and working via Groq.",
    )

    tracker = ProviderHealthTracker()
    strategy = PriorityFallbackStrategy(["gemini", "groq"])
    router = ModelRouter(providers=[gemini, groq], strategy=strategy, tracker=tracker)

    orchestrator = CompanionOrchestrator(router=router)
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

    manager.capture.capture_turn = AsyncMock(return_value=b"DUMMY_AUDIO_BYTES")
    stt.set_transcription_text("How are you today?")

    should_continue = asyncio.run(manager.process_one_turn())

    assert should_continue is True  # Voice loop stays active!
    assert tts.synthesize_call_count >= 1  # Speech was synthesized for the user
    assert groq.stream_call_count == 1   # Groq fulfilled the stream
    assert tracker.get_status(gemini) == ProviderHealthStatus.QUOTA_EXHAUSTED


def test_no_api_keys_in_logs_or_errors():
    """8. Never expose API keys: SecretMaskingFilter scrubs API keys from query params and strings."""
    sensitive_url = "https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent?key=AIzaSyD_TEST_SECRET_KEY_12345678"
    sanitized = sanitize_text(sensitive_url)

    assert "AIzaSyD_TEST_SECRET_KEY_12345678" not in sanitized
    assert "***REDACTED***" in sanitized

    sensitive_groq = "Authorization failed for key: gsk_1234567890abcdef1234567890abcdef12345678"
    sanitized_groq = sanitize_text(sensitive_groq)
    assert "gsk_1234567890abcdef1234567890abcdef12345678" not in sanitized_groq
    assert "***REDACTED***" in sanitized_groq


def test_fallback_provider_success(sample_request: AIRequest):
    """Verify fallback provider success when primary fails."""
    gemini = MockStreamingProvider("gemini", fail_with=ProviderQuotaExceededError("Gemini 429"))
    groq = MockStreamingProvider("groq", return_content="Groq handled this successfully!")

    tracker = ProviderHealthTracker()
    strategy = PriorityFallbackStrategy(["gemini", "groq"])
    router = ModelRouter(providers=[gemini, groq], strategy=strategy, tracker=tracker)

    resp = asyncio.run(router.route(sample_request))
    assert resp.content == "Groq handled this successfully!"
    assert resp.metadata["provider"] == "groq"
    assert tracker.get_status(gemini) == ProviderHealthStatus.QUOTA_EXHAUSTED
    assert tracker.get_status(groq) == ProviderHealthStatus.AVAILABLE


def test_provider_health_state_transitions():
    """Verify provider health states: AVAILABLE, TEMPORARILY_UNAVAILABLE, QUOTA_EXHAUSTED, ERROR."""
    provider = MockStreamingProvider("test-provider")
    tracker = ProviderHealthTracker(default_cooldown_seconds=10.0)

    # Initially AVAILABLE
    assert tracker.get_status(provider) == ProviderHealthStatus.AVAILABLE

    # QUOTA_EXHAUSTED
    tracker.record_quota_exhausted("test-provider", cooldown_seconds=5.0, error="Quota exceeded")
    assert tracker.get_status(provider) == ProviderHealthStatus.QUOTA_EXHAUSTED

    # TEMPORARILY_UNAVAILABLE
    tracker.record_temporarily_unavailable("test-provider", cooldown_seconds=5.0, error="Service busy")
    assert tracker.get_status(provider) == ProviderHealthStatus.TEMPORARILY_UNAVAILABLE

    # ERROR
    tracker.record_error("test-provider", error="Fatal upstream error")
    assert tracker.get_status(provider) == ProviderHealthStatus.ERROR

    # Reset to AVAILABLE via record_success
    tracker.record_success("test-provider")
    assert tracker.get_status(provider) == ProviderHealthStatus.AVAILABLE


def test_generic_429_resource_exhausted_string_recognized(sample_request: AIRequest):
    """Verify any error string containing 429 RESOURCE_EXHAUSTED is recognized as quota exhaustion."""
    generic_err = Exception("429 RESOURCE_EXHAUSTED generate_content_free_tier_requests model: gemini-2.5-flash")
    gemini = MockStreamingProvider("gemini", fail_with=generic_err)
    groq = MockStreamingProvider("groq", return_content="Groq fallback output")

    tracker = ProviderHealthTracker()
    strategy = PriorityFallbackStrategy(["gemini", "groq"])
    router = ModelRouter(providers=[gemini, groq], strategy=strategy, tracker=tracker)

    resp = asyncio.run(router.route(sample_request))
    assert resp.content == "Groq fallback output"
    assert tracker.get_status(gemini) == ProviderHealthStatus.QUOTA_EXHAUSTED


def test_llm_intent_planning_after_gemini_429(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Verify that when Gemini fails with 429 during intent understanding, fallback provider processes intent and tool executes."""
    monkeypatch.setenv("HOME", str(tmp_path))
    desktop_dir = tmp_path / "Desktop"
    desktop_dir.mkdir(parents=True, exist_ok=True)

    # When intent is being parsed via LLM, Gemini fails with 429; Groq returns the action plan JSON!
    intent_json = (
        '{"intent": "create_folder", "steps": ['
        '{"tool": "filesystem.create_directory", "arguments": {"action": "create_directory", "path": "~/Desktop/Projects"}, "description": "Create Projects on Desktop"}'
        ']}'
    )
    gemini = MockStreamingProvider(
        "gemini",
        fail_with=ProviderQuotaExceededError("429 RESOURCE_EXHAUSTED generate_content_free_tier_requests model: gemini-2.5-flash"),
    )
    groq = MockStreamingProvider(
        "groq",
        return_content=intent_json,
    )

    tracker = ProviderHealthTracker()
    strategy = PriorityFallbackStrategy(["gemini", "groq"])
    router = ModelRouter(providers=[gemini, groq], strategy=strategy, tracker=tracker)

    from lyra.companion.planner import ActionPlanner
    planner = ActionPlanner(router=router)
    session = Session()

    # Query that doesn't match standard regex, triggering plan_async
    plan = asyncio.run(planner.plan_async("Set up an empty folder named Projects on my desktop area", session=session))

    assert plan is not None
    assert plan.intent == "create_folder"
    assert len(plan.steps) == 1
    assert plan.steps[0].tool == "filesystem.create_directory"
    assert str(desktop_dir / "Projects") in plan.steps[0].arguments["path"]
    assert tracker.get_status(gemini) == ProviderHealthStatus.QUOTA_EXHAUSTED


def test_action_execution_when_all_providers_quota_exhausted(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Verify that when all AI providers are exhausted, the tool action still executes and returns deterministic reply."""
    monkeypatch.setenv("HOME", str(tmp_path))
    desktop_dir = tmp_path / "Desktop"
    desktop_dir.mkdir(parents=True, exist_ok=True)

    gemini = MockStreamingProvider(
        "gemini",
        fail_with=ProviderQuotaExceededError("429 RESOURCE_EXHAUSTED free tier exceeded"),
    )
    groq = MockStreamingProvider(
        "groq",
        fail_with=ProviderQuotaExceededError("429 Groq rate limit exceeded"),
    )

    tracker = ProviderHealthTracker()
    strategy = PriorityFallbackStrategy(["gemini", "groq"])
    router = ModelRouter(providers=[gemini, groq], strategy=strategy, tracker=tracker)

    filesystem_tool = FilesystemTool(default_base_dir=desktop_dir)
    registry = ToolRegistry(tools=[filesystem_tool])
    executor = ToolExecutor(registry=registry)

    orchestrator = CompanionOrchestrator(
        router=router,
        tool_registry=registry,
        tool_executor=executor,
    )
    session = Session()

    reply = asyncio.run(orchestrator.process_turn(session, "Lyra, create a folder named Projects on my desktop."))

    # 1. Action was still executed!
    expected_folder = desktop_dir / "Projects"
    assert expected_folder.exists()
    assert expected_folder.is_dir()

    # 2. Friendly deterministic reply returned (no tracebacks or errors shown to user)
    assert "Projects" in reply
    assert "Done, I created" in reply
    assert "Traceback" not in reply
    assert "429" not in reply


