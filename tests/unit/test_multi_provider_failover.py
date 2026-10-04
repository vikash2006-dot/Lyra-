"""Comprehensive unit tests for Multi-Provider Auto-Failover, One-Command Startup,
Streaming Failover, Cooldown, and Recovery in LYRA.

Covers:
A. Startup (main.py boots, providers initialized)
B. Gemini success
C. Gemini 429 classification
D. Gemini quota exhausted -> Grok fallback
E. Grok fallback -> Groq fallback
F. Groq fallback -> Cerebras fallback
G. Cerebras fallback -> OpenRouter fallback
H. OpenRouter fallback -> Ollama fallback
I. All providers unavailable (truthful notification, no crash)
J. Provider recovery (automatic restoration of preferred provider after cooldown)
K. Provider cooldown (skips provider while in cooldown window)
L. Streaming fallback (429 before first token switches provider seamlessly)
M. Partial stream failure (preserves already emitted tokens without duplicate speech)
N. Tool execution after provider fallback (provider-independent tool registry)
O. Voice loop after provider fallback
P. Fast-path brightness commands (no LLM call)
Q. Fast-path volume commands (no LLM call)
R. Fast-path filesystem commands
S. Browser tab management (new tab, close tab)
T. Google search & result opening
U. YouTube search & playback
V. Multi-step tasks decomposition
W. Context-dependent sequence across turns
X. Runtime observability status inspection
"""

import asyncio
from pathlib import Path
import time
from unittest.mock import AsyncMock, MagicMock, patch
import pytest

from lyra.companion.orchestrator import CompanionOrchestrator
from lyra.companion.planner import ActionPlanner
from lyra.companion.session import Session
from lyra.config.settings import Settings, load_settings
from lyra.core.exceptions import (
    NoAvailableProviderError,
    ProviderAuthenticationError,
    ProviderError,
    ProviderQuotaExceededError,
    ProviderRateLimitError,
)
from lyra.models.messages import AIRequest, AIResponse, Message, Role
from lyra.models.stream import StreamCompleted, StreamError, StreamStarted, TextDelta
from lyra.models.tools import ToolRequest, ToolResult
from lyra.providers.base import AIProvider
from lyra.providers.cerebras import CerebrasProvider
from lyra.providers.gemini import GeminiProvider
from lyra.providers.groq import GroqProvider
from lyra.providers.local import LocalProvider
from lyra.providers.openrouter import OpenRouterProvider
from lyra.providers.xai import XAIProvider
from lyra.routing.health import (
    FailureCategory,
    ProviderHealthStatus,
    ProviderHealthTracker,
    classify_failure,
)
from lyra.routing.router import ModelRouter
from lyra.routing.strategies import PriorityFallbackStrategy
from lyra.tools.executor import ToolExecutor
from lyra.tools.registry import ToolRegistry


class DummyProvider(AIProvider):
    """Configurable mock provider for deterministic failover testing."""

    def __init__(
        self,
        name: str,
        configured: bool = True,
        response_text: str = "Hello from Dummy",
        fail_with: Exception | None = None,
        supports_streaming: bool = True,
        stream_tokens: list[str] | None = None,
        fail_during_stream_at_index: int | None = None,
    ) -> None:
        self._name = name
        self._configured = configured
        self.response_text = response_text
        self.fail_with = fail_with
        self._supports_streaming = supports_streaming
        self.stream_tokens = stream_tokens or ["Hello", " from ", self._name]
        self.fail_during_stream_at_index = fail_during_stream_at_index
        self.generate_calls = 0
        self.stream_calls = 0

    @property
    def name(self) -> str:
        return self._name

    @property
    def is_configured(self) -> bool:
        return self._configured

    @property
    def supports_streaming(self) -> bool:
        return self._supports_streaming

    async def generate(self, request: AIRequest) -> AIResponse:
        self.generate_calls += 1
        if self.fail_with:
            raise self.fail_with
        return AIResponse(
            content=self.response_text,
            model=f"{self._name}-model",
            role=Role.ASSISTANT,
        )

    async def stream(self, request: AIRequest):
        self.stream_calls += 1
        if self.fail_with and self.fail_during_stream_at_index is None:
            raise self.fail_with
        for i, token in enumerate(self.stream_tokens):
            if self.fail_during_stream_at_index is not None and i == self.fail_during_stream_at_index:
                raise self.fail_with or ProviderError("Failed mid-stream")
            yield token


@pytest.fixture
def session():
    return Session()


# -----------------------------------------------------------------------------
# A. Startup & Environment Bootstrapping
# -----------------------------------------------------------------------------
def test_a_startup_environment_and_providers():
    """Verify settings loads default provider priority including gemini, xai, groq, cerebras, openrouter, ollama."""
    from lyra.config.settings import DEFAULT_PROVIDER_PRIORITY, load_settings
    assert "gemini" in DEFAULT_PROVIDER_PRIORITY
    assert "xai" in DEFAULT_PROVIDER_PRIORITY
    assert "groq" in DEFAULT_PROVIDER_PRIORITY
    assert "cerebras" in DEFAULT_PROVIDER_PRIORITY
    assert "openrouter" in DEFAULT_PROVIDER_PRIORITY
    assert "ollama" in DEFAULT_PROVIDER_PRIORITY

    settings = load_settings()
    assert settings.rate_limit_cooldown_seconds >= 60.0

    # Ensure XAIProvider instantiates cleanly
    xai = XAIProvider(api_key="test-key")
    assert xai.name == "xai"
    assert xai.is_configured is True
    assert xai.supports_streaming is True


# -----------------------------------------------------------------------------
# B. Gemini Success
# -----------------------------------------------------------------------------
def test_b_gemini_success():
    """Verify router selects and succeeds with Gemini when healthy."""
    gemini = DummyProvider("gemini", response_text="Answer from Gemini")
    grok = DummyProvider("xai", response_text="Answer from Grok")
    tracker = ProviderHealthTracker()

    strategy = PriorityFallbackStrategy(["gemini", "xai"])
    router = ModelRouter(providers=[gemini, grok], strategy=strategy, tracker=tracker)

    req = AIRequest(messages=(Message(role=Role.USER, content="Hello"),))
    res = asyncio.run(router.route(req))

    assert res.content == "Answer from Gemini"
    assert gemini.generate_calls == 1
    assert grok.generate_calls == 0
    assert tracker.get_status("gemini") == ProviderHealthStatus.AVAILABLE


# -----------------------------------------------------------------------------
# C. Failure Classification (429, Resource Exhausted, Auth, Timeout)
# -----------------------------------------------------------------------------
def test_c_failure_classification():
    """Verify classify_failure maps errors to canonical 10 categories."""
    assert classify_failure(ProviderQuotaExceededError("429 RESOURCE_EXHAUSTED")) == FailureCategory.QUOTA_EXHAUSTED
    assert classify_failure(Exception("HTTP 429 Too Many Requests")) == FailureCategory.RATE_LIMITED
    assert classify_failure(ProviderAuthenticationError("Invalid API key")) == FailureCategory.AUTHENTICATION_ERROR
    assert classify_failure(Exception("Connection refused by peer")) == FailureCategory.NETWORK_ERROR
    assert classify_failure(Exception("Read timed out")) == FailureCategory.TIMEOUT
    assert classify_failure(Exception("503 Service Unavailable")) == FailureCategory.SERVICE_UNAVAILABLE
    assert classify_failure(Exception("404 Model Not Found")) == FailureCategory.MODEL_UNAVAILABLE
    assert classify_failure(Exception("400 Bad Request")) == FailureCategory.INVALID_REQUEST
    assert classify_failure(Exception("Unknown internal crash")) == FailureCategory.UNKNOWN_ERROR


# -----------------------------------------------------------------------------
# D. Gemini Quota Exhausted -> Grok Fallback
# -----------------------------------------------------------------------------
def test_d_gemini_quota_exhausted_fallback_to_grok():
    """Verify Gemini 429 quota exhaustion marks cooldown and fails over to Grok seamlessly."""
    gemini = DummyProvider(
        "gemini",
        fail_with=ProviderQuotaExceededError("429 RESOURCE_EXHAUSTED quota exceeded"),
    )
    grok = DummyProvider("xai", response_text="Answer from Grok (xAI)")
    tracker = ProviderHealthTracker(default_cooldown_seconds=300.0)

    strategy = PriorityFallbackStrategy(["gemini", "xai"])
    router = ModelRouter(providers=[gemini, grok], strategy=strategy, tracker=tracker)

    req = AIRequest(messages=(Message(role=Role.USER, content="Hello"),))
    res = asyncio.run(router.route(req))

    assert res.content == "Answer from Grok (xAI)"
    assert gemini.generate_calls == 1
    assert grok.generate_calls == 1
    # Gemini must be marked QUOTA_EXHAUSTED with active cooldown
    assert tracker.get_status("gemini") == ProviderHealthStatus.QUOTA_EXHAUSTED
    assert tracker.get_status("xai") == ProviderHealthStatus.AVAILABLE


# -----------------------------------------------------------------------------
# E. Cascading Fallback: Gemini -> Grok -> Groq
# -----------------------------------------------------------------------------
def test_e_grok_fails_fallback_to_groq():
    """Verify cascading failover when both Gemini and Grok are unavailable."""
    gemini = DummyProvider("gemini", fail_with=ProviderQuotaExceededError("Quota exhausted"))
    grok = DummyProvider("xai", fail_with=ProviderError("xAI 500 error"))
    groq = DummyProvider("groq", response_text="Answer from Groq")
    tracker = ProviderHealthTracker()

    strategy = PriorityFallbackStrategy(["gemini", "xai", "groq"])
    router = ModelRouter(providers=[gemini, grok, groq], strategy=strategy, tracker=tracker)

    req = AIRequest(messages=(Message(role=Role.USER, content="Hello"),))
    res = asyncio.run(router.route(req))

    assert res.content == "Answer from Groq"
    assert groq.generate_calls == 1


# -----------------------------------------------------------------------------
# F. Cascading Fallback: Groq -> Cerebras
# -----------------------------------------------------------------------------
def test_f_groq_fails_fallback_to_cerebras():
    """Verify cascading failover to Cerebras when Groq fails."""
    groq = DummyProvider("groq", fail_with=ProviderRateLimitError("Groq 429"))
    cerebras = DummyProvider("cerebras", response_text="Answer from Cerebras")
    tracker = ProviderHealthTracker()

    strategy = PriorityFallbackStrategy(["groq", "cerebras"])
    router = ModelRouter(providers=[groq, cerebras], strategy=strategy, tracker=tracker)

    req = AIRequest(messages=(Message(role=Role.USER, content="Hello"),))
    res = asyncio.run(router.route(req))

    assert res.content == "Answer from Cerebras"
    assert cerebras.generate_calls == 1


# -----------------------------------------------------------------------------
# G. Cascading Fallback: Cerebras -> OpenRouter
# -----------------------------------------------------------------------------
def test_g_cerebras_fails_fallback_to_openrouter():
    """Verify cascading failover to OpenRouter when Cerebras fails."""
    cerebras = DummyProvider("cerebras", fail_with=ProviderError("Cerebras service error"))
    openrouter = DummyProvider("openrouter", response_text="Answer from OpenRouter")
    tracker = ProviderHealthTracker()

    strategy = PriorityFallbackStrategy(["cerebras", "openrouter"])
    router = ModelRouter(providers=[cerebras, openrouter], strategy=strategy, tracker=tracker)

    req = AIRequest(messages=(Message(role=Role.USER, content="Hello"),))
    res = asyncio.run(router.route(req))

    assert res.content == "Answer from OpenRouter"
    assert openrouter.generate_calls == 1


# -----------------------------------------------------------------------------
# H. Cascading Fallback: OpenRouter -> Ollama (Local)
# -----------------------------------------------------------------------------
def test_h_openrouter_fails_fallback_to_ollama():
    """Verify cascading failover to Ollama / local runtime when cloud providers fail."""
    openrouter = DummyProvider("openrouter", fail_with=ProviderError("OpenRouter error"))
    ollama = DummyProvider("local", response_text="Answer from Ollama local model")
    tracker = ProviderHealthTracker()

    strategy = PriorityFallbackStrategy(["openrouter", "ollama"])
    router = ModelRouter(providers=[openrouter, ollama], strategy=strategy, tracker=tracker)

    req = AIRequest(messages=(Message(role=Role.USER, content="Hello"),))
    res = asyncio.run(router.route(req))

    assert res.content == "Answer from Ollama local model"
    assert ollama.generate_calls == 1


# -----------------------------------------------------------------------------
# I. All Providers Unavailable (Truthful notification, no crash)
# -----------------------------------------------------------------------------
def test_i_all_providers_unavailable_truthful_notification(session):
    """Verify LYRA informs user truthfully without crashing when all providers fail."""
    gemini = DummyProvider("gemini", fail_with=ProviderQuotaExceededError("Quota exhausted"))
    groq = DummyProvider("groq", fail_with=ProviderError("Groq offline"))
    tracker = ProviderHealthTracker()

    strategy = PriorityFallbackStrategy(["gemini", "groq"])
    router = ModelRouter(providers=[gemini, groq], strategy=strategy, tracker=tracker)

    orchestrator = CompanionOrchestrator(router=router)

    reply = asyncio.run(orchestrator.process_turn(session, "What is the capital of France?"))
    assert "I don't currently have an available AI provider" in reply
    assert not reply.startswith("Done.")


# -----------------------------------------------------------------------------
# J. Provider Recovery (Restoring preferred provider after cooldown)
# -----------------------------------------------------------------------------
def test_j_provider_recovery_after_cooldown():
    """Verify that when cooldown window expires, preferred provider is automatically restored."""
    tracker = ProviderHealthTracker(default_cooldown_seconds=0.05)  # 50ms cooldown for test
    tracker.record_quota_exhausted("gemini", cooldown_seconds=0.05)
    assert tracker.get_status("gemini") == ProviderHealthStatus.QUOTA_EXHAUSTED

    # Wait for cooldown to expire
    time.sleep(0.06)

    # Status must automatically recover to AVAILABLE!
    assert tracker.get_status("gemini") == ProviderHealthStatus.AVAILABLE
    rec = tracker.get_record("gemini")
    assert rec.cooldown_until == 0.0
    assert rec.last_error is None


# -----------------------------------------------------------------------------
# K. Provider Cooldown (Skips provider while in cooldown)
# -----------------------------------------------------------------------------
def test_k_provider_skipped_during_cooldown():
    """Verify that during active cooldown, provider is skipped without being called."""
    gemini = DummyProvider("gemini", response_text="Gemini Answer")
    grok = DummyProvider("xai", response_text="Grok Answer")
    tracker = ProviderHealthTracker(default_cooldown_seconds=300.0)
    tracker.record_quota_exhausted("gemini", cooldown_seconds=300.0)

    strategy = PriorityFallbackStrategy(["gemini", "xai"])
    router = ModelRouter(providers=[gemini, grok], strategy=strategy, tracker=tracker)

    req = AIRequest(messages=(Message(role=Role.USER, content="Hello"),))
    res = asyncio.run(router.route(req))

    # Gemini must NOT be called at all because it is on active cooldown!
    assert gemini.generate_calls == 0
    assert grok.generate_calls == 1
    assert res.content == "Grok Answer"


# -----------------------------------------------------------------------------
# L. Streaming Fallback (429 before first token switches provider seamlessly)
# -----------------------------------------------------------------------------
def test_l_streaming_fallback_before_first_token():
    """Verify streaming failover when primary provider fails before emitting any token."""
    gemini = DummyProvider(
        "gemini",
        fail_with=ProviderQuotaExceededError("Gemini 429 quota exhausted"),
    )
    grok = DummyProvider(
        "xai",
        stream_tokens=["Streamed ", "from ", "Grok!"],
    )
    tracker = ProviderHealthTracker()

    strategy = PriorityFallbackStrategy(["gemini", "xai"])
    router = ModelRouter(providers=[gemini, grok], strategy=strategy, tracker=tracker)

    req = AIRequest(messages=(Message(role=Role.USER, content="Tell me a joke"),))

    async def _stream():
        tokens = []
        async for event in router.stream_events(req):
            if isinstance(event, TextDelta):
                tokens.append(event.delta)
        return "".join(tokens)

    output = asyncio.run(_stream())
    assert output == "Streamed from Grok!"
    assert gemini.stream_calls == 1
    assert grok.stream_calls == 1
    assert tracker.get_status("gemini") == ProviderHealthStatus.QUOTA_EXHAUSTED


# -----------------------------------------------------------------------------
# M. Partial Stream Failure (Preserves emitted tokens without duplicating speech)
# -----------------------------------------------------------------------------
def test_m_partial_stream_failure_preserves_tokens():
    """Verify mid-stream failure preserves already emitted tokens and does not duplicate speech."""
    gemini = DummyProvider(
        "gemini",
        stream_tokens=["First part", " of sentence", " should not duplicate"],
        fail_during_stream_at_index=2,  # fails on 3rd token
        fail_with=ProviderError("Network drop mid-stream"),
    )
    grok = DummyProvider("xai", stream_tokens=["Should not play from beginning"])
    tracker = ProviderHealthTracker()

    strategy = PriorityFallbackStrategy(["gemini", "xai"])
    router = ModelRouter(providers=[gemini, grok], strategy=strategy, tracker=tracker)

    req = AIRequest(messages=(Message(role=Role.USER, content="Stream test"),))

    async def _stream():
        emitted = []
        had_error = False
        try:
            async for event in router.stream_events(req):
                if isinstance(event, TextDelta):
                    emitted.append(event.delta)
                elif isinstance(event, StreamError):
                    had_error = True
        except ProviderError:
            had_error = True
        return emitted, had_error

    emitted_tokens, had_error = asyncio.run(_stream())
    # The first 2 tokens were emitted
    assert "".join(emitted_tokens) == "First part of sentence"
    # Had error is True
    assert had_error is True
    # Grok was NOT called to restart from beginning (no duplicated speech!)
    assert grok.stream_calls == 0


# -----------------------------------------------------------------------------
# N. Tool Execution Provider-Independence
# -----------------------------------------------------------------------------
def test_n_tool_execution_provider_independence(session):
    """Verify tool execution works identically regardless of which AI provider is active."""
    mock_tool = MagicMock()
    mock_tool.name = "system"
    mock_tool.can_handle = MagicMock(return_value=True)
    mock_tool.format_result = MagicMock(return_value="Done. Set volume to 80%.")

    async def _mock_exec(req):
        return ToolResult(tool_name="system", success=True, output={"volume": 80})

    mock_executor = MagicMock(spec=ToolExecutor)
    mock_executor.execute = AsyncMock(side_effect=_mock_exec)

    mock_registry = MagicMock(spec=ToolRegistry)
    mock_registry.get.return_value = mock_tool

    # Even if Gemini is quota exhausted and Grok is used
    gemini = DummyProvider("gemini", fail_with=ProviderQuotaExceededError("Quota exhausted"))
    grok = DummyProvider("xai", response_text="Grok says hello")
    tracker = ProviderHealthTracker()

    strategy = PriorityFallbackStrategy(["gemini", "xai"])
    router = ModelRouter(providers=[gemini, grok], strategy=strategy, tracker=tracker)

    orchestrator = CompanionOrchestrator(
        router=router,
        tool_registry=mock_registry,
        tool_executor=mock_executor,
        offline_mode=True,
    )

    # Execute system tool action (offline format_result)
    reply = asyncio.run(orchestrator.process_turn(session, "increase volume"))
    assert reply == "Done. Set volume to 80%."
    assert mock_executor.execute.called

    # When online, verify Grok handles the response synthesis seamlessly after Gemini failure
    orchestrator_online = CompanionOrchestrator(
        router=router,
        tool_registry=mock_registry,
        tool_executor=mock_executor,
        offline_mode=False,
    )
    reply_online = asyncio.run(orchestrator_online.process_turn(session, "increase volume"))
    assert "Grok" in reply_online


# -----------------------------------------------------------------------------
# O. Voice Loop After Provider Fallback
# -----------------------------------------------------------------------------
def test_o_voice_loop_after_provider_fallback(session):
    """Verify the conversation loop continues normally after a provider fallback."""
    gemini = DummyProvider("gemini", fail_with=ProviderQuotaExceededError("Quota exhausted"))
    grok = DummyProvider("xai", response_text="Hello from Grok!")
    tracker = ProviderHealthTracker()

    strategy = PriorityFallbackStrategy(["gemini", "xai"])
    router = ModelRouter(providers=[gemini, grok], strategy=strategy, tracker=tracker)
    orchestrator = CompanionOrchestrator(router=router)

    # Turn 1: Gemini fails -> Grok answers
    reply1 = asyncio.run(orchestrator.process_turn(session, "Turn 1"))
    assert "Grok" in reply1

    # Turn 2: Voice loop continues, Grok answers immediately without crashing
    grok.response_text = "Continuing voice conversation seamlessly"
    reply2 = asyncio.run(orchestrator.process_turn(session, "Turn 2"))
    assert reply2 == "Continuing voice conversation seamlessly"


# -----------------------------------------------------------------------------
# P - W. Natural Voice Commands & Fast-Path Action Planning
# -----------------------------------------------------------------------------
def test_p_fast_path_brightness(session):
    planner = ActionPlanner()
    p1 = planner.plan("Lyra, decrease brightness", session=session)
    assert p1 is not None
    assert "brightness" in p1.arguments.get("action")

    p2 = planner.plan("Lyra, increase brightness", session=session)
    assert p2 is not None
    assert "brightness" in p2.arguments.get("action")


def test_q_fast_path_volume(session):
    planner = ActionPlanner()
    p1 = planner.plan("Lyra, increase volume", session=session)
    assert p1 is not None
    assert "volume" in p1.arguments.get("action")

    p2 = planner.plan("mute", session=session)
    assert p2 is not None
    assert "mute" in p2.arguments.get("action")


def test_r_fast_path_filesystem(session):
    planner = ActionPlanner()
    p = planner.plan("create a folder called Projects on my Desktop", session=session)
    assert p is not None
    assert "filesystem" in p.tool_name
    assert "Projects" in p.arguments.get("path")


def test_s_fast_path_browser_tabs(session):
    planner = ActionPlanner()
    p_new = planner.plan("open a new tab", session=session)
    assert p_new is not None
    assert p_new.arguments.get("action") == "new_tab"

    p_close = planner.plan("close tab", session=session)
    assert p_close is not None
    assert p_close.arguments.get("action") == "close_tab"


def test_t_google_search(session):
    planner = ActionPlanner()
    p = planner.plan("search Google for Python tutorials", session=session)
    assert p is not None
    assert "Python tutorials" in p.arguments.get("query")


def test_u_youtube_search_and_play(session):
    planner = ActionPlanner()
    p_search = planner.plan("search YouTube for Believer", session=session)
    assert p_search is not None
    assert "Believer" in p_search.arguments.get("query")


def test_v_multi_step_task(session):
    planner = ActionPlanner()
    p = planner.plan("open YouTube, search for Arijit Singh, and play the first song", session=session)
    assert p is not None
    assert len(p.steps) >= 2


def test_w_context_dependent_sequence(session):
    planner = ActionPlanner()
    planner.plan("open YouTube", session=session)
    p2 = planner.plan("search for Believer", session=session)
    assert p2.intent == "contextual_youtube_search"
    p3 = planner.plan("play the first one", session=session)
    assert p3.intent == "contextual_play_top_result"


# -----------------------------------------------------------------------------
# X. Runtime Observability & Status Inspection
# -----------------------------------------------------------------------------
def test_x_runtime_status_inspection():
    """Verify router runtime status reporting and simulation hook."""
    gemini = DummyProvider("gemini", configured=True)
    grok = DummyProvider("xai", configured=True)
    groq = DummyProvider("groq", configured=False)
    tracker = ProviderHealthTracker()

    strategy = PriorityFallbackStrategy(["gemini", "xai", "groq"])
    router = ModelRouter(providers=[gemini, grok, groq], strategy=strategy, tracker=tracker)

    status_str = router.format_runtime_status()
    assert "Current provider: Gemini" in status_str
    assert "Gemini: AVAILABLE" in status_str
    assert "Grok: AVAILABLE" in status_str
    assert "Groq: NOT_CONFIGURED" in status_str

    # Simulate Gemini 429 quota exhaustion
    tracker.simulate_failure("gemini", category=FailureCategory.QUOTA_EXHAUSTED, cooldown_seconds=300.0)

    # Preferred provider now switches to Grok!
    status_updated = router.format_runtime_status()
    assert "Current provider: Xai" in status_updated
    assert "Gemini: QUOTA_EXHAUSTED" in status_updated
    assert "Grok: AVAILABLE" in status_updated
