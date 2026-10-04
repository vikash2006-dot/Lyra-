"""Routing strategies for selecting AI providers in LYRA."""

from abc import ABC, abstractmethod
from typing import Sequence

from lyra.config.settings import load_settings
from lyra.models.messages import AIRequest
from lyra.providers.base import AIProvider
from lyra.routing.health import ProviderHealthStatus, ProviderHealthTracker


class RoutingStrategy(ABC):
    """Abstract base class for provider routing strategies."""

    @abstractmethod
    def select_candidates(
        self,
        providers: Sequence[AIProvider],
        request: AIRequest,
        tracker: ProviderHealthTracker,
    ) -> list[AIProvider]:
        """Return an ordered list of candidate providers to attempt for the given request."""


class PriorityFallbackStrategy(RoutingStrategy):
    """Free-first deterministic priority routing strategy with fallback support.

    Orders providers by:
    1. User preferred provider (if specified in request metadata and healthy/configured).
    2. Task type optimizations (e.g. low-latency preference for 'fast' tasks).
    3. Configurable priority order (default: Gemini -> Groq -> OpenRouter -> Cerebras).
    4. Rate-limited providers (deprioritized as last-ditch fallbacks).
    5. Excludes NOT_CONFIGURED providers.
    """

    def __init__(
        self,
        priority_order: Sequence[str] | None = None,
        offline_mode: bool | None = None,
    ) -> None:
        settings = load_settings()
        if priority_order is not None:
            self._priority_order = tuple(p.lower().strip() for p in priority_order)
        else:
            self._priority_order = settings.provider_priority

        self._offline_mode = offline_mode if offline_mode is not None else settings.offline_mode

    @property
    def priority_order(self) -> tuple[str, ...]:
        return self._priority_order

    @property
    def offline_mode(self) -> bool:
        return self._offline_mode

    def select_candidates(
        self,
        providers: Sequence[AIProvider],
        request: AIRequest,
        tracker: ProviderHealthTracker,
    ) -> list[AIProvider]:
        provider_map = {p.name.lower(): p for p in providers}
        if "local" in provider_map and "ollama" not in provider_map:
            provider_map["ollama"] = provider_map["local"]
        if "ollama" in provider_map and "local" not in provider_map:
            provider_map["local"] = provider_map["ollama"]
        if "xai" in provider_map and "grok" not in provider_map:
            provider_map["grok"] = provider_map["xai"]
        if "grok" in provider_map and "xai" not in provider_map:
            provider_map["xai"] = provider_map["grok"]

        # 1. Inspect user preference from metadata
        user_pref = (
            request.metadata.get("preferred_provider")
            or request.metadata.get("provider")
        )
        preferred_name = str(user_pref).lower().strip() if user_pref else None

        # 2. Inspect task type from metadata
        task_type = str(request.metadata.get("task_type", "")).lower().strip()

        # Build effective priority order
        order: list[str] = []

        # If user explicitly preferred a known provider, place it first
        if preferred_name and preferred_name in provider_map:
            order.append(preferred_name)

        # If task is 'fast', prioritize ultra-low latency providers if present
        if task_type in ("fast", "realtime", "speed"):
            for fast_provider in ("cerebras", "groq"):
                if fast_provider in provider_map and fast_provider not in order:
                    order.append(fast_provider)

        # If task is a complex workflow or research, prioritize anakin
        if task_type in ("workflow", "complex_workflow", "complex", "research", "anakin_workflow", "anakin"):
            if "anakin" in provider_map and "anakin" not in order:
                order.append("anakin")

        # If task is private or local, prioritize local/ollama
        if task_type in ("local", "private", "offline"):
            for local_name in ("local", "ollama"):
                if local_name in provider_map and local_name not in order:
                    order.append(local_name)

        # Append remaining providers according to configured priority
        for name in self._priority_order:
            if name in provider_map and name not in order:
                order.append(name)

        # Append any registered providers not in priority order
        for name in provider_map:
            if name not in order:
                order.append(name)

        # 3. Categorize candidates based on health status
        available_candidates: list[AIProvider] = []
        quota_exhausted_candidates: list[AIProvider] = []
        unavailable_candidates: list[AIProvider] = []

        is_offline = self._offline_mode or bool(request.metadata.get("offline_mode", False))

        seen_candidates: set[int] = set()
        for name in order:
            provider = provider_map[name]
            if id(provider) in seen_candidates:
                continue
            seen_candidates.add(id(provider))

            # In offline mode, completely exclude external cloud providers
            if is_offline and name in ("gemini", "xai", "grok", "groq", "openrouter", "cerebras", "anakin"):
                continue

            # Modality capability checks
            if request.has_images() and not provider.supports_vision:
                continue
            if request.has_audio() and not provider.supports_audio:
                continue
            if request.has_files() and not provider.supports_files:
                continue

            status = tracker.get_status(provider)

            if status == ProviderHealthStatus.NOT_CONFIGURED:
                # Never attempt unconfigured providers
                continue

            if status == ProviderHealthStatus.AVAILABLE:
                available_candidates.append(provider)
            elif status in (
                ProviderHealthStatus.QUOTA_EXHAUSTED,
                ProviderHealthStatus.RATE_LIMITED,
            ):
                # Quota exhausted / rate-limited providers are skipped when healthy providers exist
                quota_exhausted_candidates.append(provider)
            elif status in (
                ProviderHealthStatus.TEMPORARILY_UNAVAILABLE,
                ProviderHealthStatus.UNAVAILABLE,
                ProviderHealthStatus.AUTH_FAILED,
                ProviderHealthStatus.ERROR,
            ):
                unavailable_candidates.append(provider)

        # If any configured providers are healthy and available, prioritize them exclusively
        if available_candidates:
            return available_candidates

        # When all providers are degraded, return unavailable then quota-exhausted as last resort
        return unavailable_candidates + quota_exhausted_candidates
