"""Intelligent Model Router for LYRA."""

import asyncio
from typing import Sequence

from lyra.config.settings import load_settings
from lyra.core.exceptions import (
    NoAvailableProviderError,
    ProviderAuthenticationError,
    ProviderError,
    ProviderQuotaExceededError,
    ProviderRateLimitError,
)
from lyra.models.messages import AIRequest, AIResponse
from lyra.observability.logging import get_logger, sanitize_text
from lyra.providers.base import AIProvider
from lyra.routing.health import FailureCategory, ProviderHealthStatus, ProviderHealthTracker
from lyra.routing.strategies import PriorityFallbackStrategy, RoutingStrategy


def _is_quota_exhaustion_error(err: Exception) -> bool:
    """Detect if an exception represents HTTP 429 / RESOURCE_EXHAUSTED / quota exceeded."""
    if isinstance(err, ProviderQuotaExceededError):
        return True
    err_str = str(err).upper()
    return (
        "RESOURCE_EXHAUSTED" in err_str
        or "FREE_TIER_REQUESTS" in err_str
        or "QUOTA EXCEEDED" in err_str
        or "QUOTA_EXHAUSTED" in err_str
        or "QUOTA" in err_str
    )


def _is_rate_limit_error(err: Exception) -> bool:
    """Detect if an exception represents general rate limiting (HTTP 429)."""
    if isinstance(err, ProviderRateLimitError):
        return True
    err_str = str(err).upper()
    return "429" in err_str or "RATE_LIMIT" in err_str or "RATE LIMIT" in err_str


class ModelRouter:
    """Intelligent, provider-agnostic router with fallback and health tracking."""

    def __init__(
        self,
        providers: Sequence[AIProvider] | None = None,
        strategy: RoutingStrategy | None = None,
        tracker: ProviderHealthTracker | None = None,
        offline_mode: bool | None = None,
    ) -> None:
        settings = load_settings()
        self._logger = get_logger("router")
        self._offline_mode = offline_mode if offline_mode is not None else settings.offline_mode
        self._strategy = strategy or PriorityFallbackStrategy(
            settings.provider_priority,
            offline_mode=self._offline_mode,
        )
        self._tracker = tracker or ProviderHealthTracker(
            default_cooldown_seconds=settings.rate_limit_cooldown_seconds
        )
        self._cooldown_seconds = settings.rate_limit_cooldown_seconds
        self._providers: dict[str, AIProvider] = {}

        if providers:
            for provider in providers:
                self.register_provider(provider)

    @property
    def offline_mode(self) -> bool:
        return self._offline_mode

    @offline_mode.setter
    def offline_mode(self, value: bool) -> None:
        self._offline_mode = value
        if hasattr(self._strategy, "_offline_mode"):
            self._strategy._offline_mode = value

    @property
    def strategy(self) -> RoutingStrategy:
        return self._strategy

    @property
    def tracker(self) -> ProviderHealthTracker:
        return self._tracker

    def register_provider(self, provider: AIProvider) -> None:
        """Register an AIProvider into the router pool with aliases."""
        norm_name = provider.name.lower().strip()
        self._providers[norm_name] = provider
        if norm_name == "local":
            self._providers["ollama"] = provider
        elif norm_name == "ollama":
            self._providers["local"] = provider
        elif norm_name == "xai":
            self._providers["grok"] = provider
        elif norm_name == "grok":
            self._providers["xai"] = provider
        self._logger.debug("Registered AI provider '%s' (status: %s)", provider.name, provider.status)

    def get_provider(self, name: str) -> AIProvider | None:
        """Retrieve a registered provider by name (or alias)."""
        norm = name.lower().strip()
        if norm in self._providers:
            return self._providers[norm]
        if norm in ("ollama", "local"):
            return self._providers.get("local") or self._providers.get("ollama")
        if norm in ("xai", "grok"):
            return self._providers.get("xai") or self._providers.get("grok")
        return None

    def list_providers(self) -> list[AIProvider]:
        """Return all distinct registered providers in the router pool."""
        unique: list[AIProvider] = []
        seen: set[int] = set()
        for p in self._providers.values():
            if id(p) not in seen:
                seen.add(id(p))
                unique.append(p)
        return unique

    def get_provider_status(self, provider_name: str) -> ProviderHealthStatus:
        """Get the current health status of a named provider."""
        provider = self.get_provider(provider_name)
        if not provider:
            return ProviderHealthStatus.NOT_CONFIGURED
        return self._tracker.get_status(provider)

    def get_runtime_status(self) -> dict[str, Any]:
        """Return complete runtime health and configuration status of all providers."""
        providers = self.list_providers()
        status_map = {}
        records = {}
        preferred = None

        from lyra.models.messages import Message, Role

        dummy_req = AIRequest(messages=(Message(role=Role.USER, content="status"),))
        candidates = self._strategy.select_candidates(providers, dummy_req, self._tracker)
        if candidates:
            preferred = candidates[0].name.capitalize()

        for p in providers:
            stat = self._tracker.get_status(p)
            rec = self._tracker.get_record(p.name)
            status_map[p.name] = stat.value
            records[p.name] = {
                "status": stat.value,
                "last_success": rec.last_success,
                "last_failure": rec.last_failure,
                "failure_category": rec.failure_category.value if rec.failure_category else None,
                "cooldown_until": rec.cooldown_until,
                "latency": rec.latency,
                "consecutive_failures": rec.consecutive_failures,
            }

        return {
            "current_provider": preferred or "None",
            "available_providers": [p.name for p in candidates],
            "provider_health": status_map,
            "records": records,
        }

    def format_runtime_status(self) -> str:
        """Format human-readable runtime observability report."""
        status = self.get_runtime_status()
        lines = [f"Current provider: {status['current_provider']}\n"]

        display_order = ["gemini", "xai", "groq", "cerebras", "openrouter", "anakin", "ollama"]
        for key in display_order:
            p = self.get_provider(key)
            if p:
                health = self._tracker.get_status(p).value
            else:
                health = "NOT_CONFIGURED"
            name = "Grok" if key == "xai" else ("Anakin" if key == "anakin" else ("Ollama" if key in ("ollama", "local") else key.capitalize()))
            lines.append(f"{name}: {health}")
        return "\n".join(lines)

    async def route(self, request: AIRequest) -> AIResponse:
        """Route request through available providers with cascading fallback.

        Args:
            request: Canonical AIRequest to fulfill.

        Returns:
            AIResponse from the first successful provider.

        Raises:
            NoAvailableProviderError: If all candidate providers fail or none are available.
        """
        import time
        from lyra.routing.health import classify_failure

        candidates = self._strategy.select_candidates(
            self.list_providers(),
            request,
            self._tracker,
        )

        if not candidates:
            provider_statuses = {
                p.name: self._tracker.get_status(p).value
                for p in self.list_providers()
            }
            self._logger.error("No available candidate providers. Pool status: %s", provider_statuses)
            is_offline = self._offline_mode or bool(request.metadata.get("offline_mode", False))
            if is_offline:
                raise NoAvailableProviderError(
                    f"Offline mode is active, but no local AI provider could fulfill the request. "
                    f"External cloud providers are disabled. Provider pool status: {provider_statuses}"
                )
            raise NoAvailableProviderError(
                f"No available AI provider could fulfill the request. Provider pool status: {provider_statuses}"
            )

        attempted_errors: list[str] = []

        for candidate in candidates:
            candidate_name = candidate.name
            display_name = candidate_name.capitalize()
            self._logger.info("[Provider] %s selected", display_name)

            start_t = time.time()
            try:
                response = await candidate.generate(request)
                latency = time.time() - start_t
                self._tracker.record_success(candidate_name, latency=latency)
                self._logger.info(
                    "[Provider] Request successful with %s (latency: %.2fs, model: %s)",
                    display_name,
                    latency,
                    response.model,
                )
                return response

            except Exception as err:
                clean_err = sanitize_text(str(err))
                cat = classify_failure(err)

                if _is_quota_exhaustion_error(err):
                    self._tracker.record_quota_exhausted(candidate_name, error=clean_err)
                    self._logger.warning(
                        "[Provider] %s quota exhausted (429/RESOURCE_EXHAUSTED): %s. [Provider] Switching to next candidate...",
                        display_name,
                        clean_err,
                    )
                    attempted_errors.append(f"{candidate_name} (Quota Exhausted): {clean_err}")
                elif _is_rate_limit_error(err):
                    self._tracker.record_rate_limited(candidate_name, error=clean_err)
                    self._logger.warning(
                        "[Provider] %s rate limited: %s. [Provider] Switching to next candidate...",
                        display_name,
                        clean_err,
                    )
                    attempted_errors.append(f"{candidate_name} (Rate Limited): {clean_err}")
                elif (
                    isinstance(err, ProviderAuthenticationError)
                    or cat == FailureCategory.AUTHENTICATION_ERROR
                    or "401" in str(err)
                    or "UNAUTHENTICATED" in str(err)
                    or "ACCESS_TOKEN_TYPE_UNSUPPORTED" in str(err)
                ):
                    self._tracker.record_auth_failed(candidate_name, cooldown_seconds=self._cooldown_seconds, error=clean_err)
                    self._logger.warning(
                        "[Provider] %s authentication failed (401). Marked as AUTH_FAILED (cooldown: %.0fs): %s. [Provider] Switching to next candidate...",
                        display_name,
                        self._cooldown_seconds,
                        clean_err,
                    )
                    attempted_errors.append(f"{candidate_name} (Auth Failed): {clean_err}")
                elif (
                    cat == FailureCategory.NETWORK_ERROR
                    or "connection refused" in str(err).lower()
                    or "unreachable" in str(err).lower()
                ):
                    self._tracker.record_failure(candidate_name, error=clean_err, status=ProviderHealthStatus.OFFLINE, category=cat)
                    self._logger.warning(
                        "[Provider] %s is offline or unreachable: %s. [Provider] Switching to next candidate...",
                        display_name,
                        clean_err,
                    )
                    attempted_errors.append(f"{candidate_name} (Offline): {clean_err}")
                elif isinstance(err, ProviderError):
                    self._tracker.record_failure(candidate_name, error=clean_err, category=cat)
                    self._logger.warning(
                        "[Provider] %s error: %s. [Provider] Switching to next candidate...",
                        display_name,
                        clean_err,
                    )
                    attempted_errors.append(f"{candidate_name} (Error): {clean_err}")
                else:
                    self._tracker.record_failure(candidate_name, error=clean_err, category=cat)
                    self._logger.error(
                        "[Provider] %s unexpected error: %s. [Provider] Switching to next candidate...",
                        display_name,
                        clean_err,
                    )
                    attempted_errors.append(f"{candidate_name} (Unexpected): {clean_err}")

        # All candidates in the fallback chain were exhausted
        error_summary = "; ".join(attempted_errors)
        self._logger.error("All candidate providers failed: %s", error_summary)
        raise NoAvailableProviderError(
            f"All candidate providers failed to fulfill request. Failures: [{error_summary}]"
        )

    def route_sync(self, request: AIRequest) -> AIResponse:
        """Synchronously execute route() by running the event loop."""
        return asyncio.run(self.route(request))

    async def stream(self, request: AIRequest):
        """Stream response tokens from candidate providers with fallback support."""
        candidates = self._strategy.select_candidates(
            self.list_providers(),
            request,
            self._tracker,
        )
        if not candidates:
            raise NoAvailableProviderError("No configured provider available for streaming.")

        attempted_errors: list[str] = []
        for candidate in candidates:
            if not candidate.supports_streaming:
                continue
            if candidate.name != candidates[0].name:
                self._logger.info("Selected fallback streaming provider '%s' after prior candidate failure", candidate.name)
            yielded_any = False
            try:
                async for token in candidate.stream(request):
                    yielded_any = True
                    yield token
                self._tracker.record_success(candidate.name)
                if candidate.name != candidates[0].name:
                    self._logger.info("Fallback streaming provider '%s' successfully fulfilled request.", candidate.name)
                return
            except Exception as err:
                clean_err = sanitize_text(str(err))
                if _is_quota_exhaustion_error(err):
                    self._tracker.record_quota_exhausted(candidate.name, error=clean_err)
                    attempted_errors.append(f"{candidate.name} (Quota Exhausted): {clean_err}")
                    if yielded_any:
                        raise ProviderError(f"Stream interrupted on provider '{candidate.name}': {clean_err}") from err
                    self._logger.warning(
                        "Streaming provider '%s' quota exhausted before yielding: %s. Falling back to next candidate...",
                        candidate.name,
                        clean_err,
                    )
                elif _is_rate_limit_error(err):
                    self._tracker.record_rate_limited(candidate.name, error=clean_err)
                    attempted_errors.append(f"{candidate.name} (Rate Limited): {clean_err}")
                    if yielded_any:
                        raise ProviderError(f"Stream interrupted on provider '{candidate.name}': {clean_err}") from err
                    self._logger.warning(
                        "Streaming provider '%s' rate limited before yielding: %s. Falling back to next candidate...",
                        candidate.name,
                        clean_err,
                    )
                elif (
                    isinstance(err, ProviderAuthenticationError)
                    or "401" in str(err)
                    or "UNAUTHENTICATED" in str(err)
                    or "ACCESS_TOKEN_TYPE_UNSUPPORTED" in str(err)
                ):
                    self._tracker.record_auth_failed(candidate.name, cooldown_seconds=self._cooldown_seconds, error=clean_err)
                    attempted_errors.append(f"{candidate.name} (Auth Failed): {clean_err}")
                    if yielded_any:
                        raise ProviderError(f"Stream interrupted on provider '{candidate.name}': {clean_err}") from err
                    self._logger.warning(
                        "[Provider] %s authentication failed (401) before yielding: %s. Switching to next candidate...",
                        candidate.name.capitalize(),
                        clean_err,
                    )
                else:
                    self._tracker.record_failure(candidate.name, error=clean_err)
                    attempted_errors.append(f"{candidate.name}: {clean_err}")
                    if yielded_any:
                        raise ProviderError(f"Stream interrupted on provider '{candidate.name}': {clean_err}") from err
                    self._logger.warning(
                        "Streaming provider '%s' failed before yielding: %s. Falling back to next candidate...",
                        candidate.name,
                        clean_err,
                    )

        error_summary = "; ".join(attempted_errors)
        raise NoAvailableProviderError(f"All streaming providers failed: [{error_summary}]")

    async def stream_events(
        self,
        request: AIRequest,
        cancellation_token: Any | None = None,
    ):
        """Stream typed StreamEvents (StreamStarted, TextDelta, StreamCompleted) with fallback."""
        from lyra.core.exceptions import StreamInterruptedError
        from lyra.models.stream import StreamCompleted, StreamError, StreamStarted, TextDelta

        candidates = self._strategy.select_candidates(
            self.list_providers(),
            request,
            self._tracker,
        )
        if not candidates:
            raise NoAvailableProviderError("No configured provider available for streaming.")

        attempted_errors: list[str] = []
        for candidate in candidates:
            if not candidate.supports_streaming:
                continue

            display_name = candidate.name.capitalize()
            self._logger.info("[Provider] %s selected for streaming", display_name)

            yielded_any = False
            yielded_started = False
            model = request.model or getattr(candidate, "_default_model", candidate.name)
            accumulated: list[str] = []
            idx = 0

            try:
                async for token in candidate.stream(request):
                    if not yielded_started:
                        yield StreamStarted(provider=candidate.name, model=model)
                        yielded_started = True
                        yielded_any = True

                    if cancellation_token and cancellation_token.is_cancelled:
                        raise StreamInterruptedError(cancellation_token.reason or "Stream cancelled by user.")
                    accumulated.append(token)
                    yield TextDelta(delta=token, index=idx)
                    idx += 1

                if not yielded_started:
                    yield StreamStarted(provider=candidate.name, model=model)
                self._tracker.record_success(candidate.name)
                self._logger.info("[Provider] Streaming fulfilled by %s.", display_name)
                yield StreamCompleted(full_text="".join(accumulated))
                return

            except StreamInterruptedError as cancel_err:
                yield StreamError(error_message=str(cancel_err), recoverable=False)
                raise
            except Exception as err:
                clean_err = sanitize_text(str(err))
                if _is_quota_exhaustion_error(err):
                    self._tracker.record_quota_exhausted(candidate.name, error=clean_err)
                    attempted_errors.append(f"{candidate.name} (Quota Exhausted): {clean_err}")
                    if len(accumulated) > 0:
                        yield StreamError(error_message=f"Stream interrupted on {candidate.name}", recoverable=False)
                        raise ProviderError(f"Stream interrupted on provider '{candidate.name}'") from err
                    self._logger.warning(
                        "[Provider] %s quota exhausted before emitting text: %s. [Provider] Switching to next candidate...",
                        display_name,
                        clean_err,
                    )
                elif _is_rate_limit_error(err):
                    self._tracker.record_rate_limited(candidate.name, error=clean_err)
                    attempted_errors.append(f"{candidate.name} (Rate Limited): {clean_err}")
                    if len(accumulated) > 0:
                        yield StreamError(error_message=f"Stream interrupted on {candidate.name}", recoverable=False)
                        raise ProviderError(f"Stream interrupted on provider '{candidate.name}'") from err
                    self._logger.warning(
                        "[Provider] %s rate limited before emitting text: %s. [Provider] Switching to next candidate...",
                        display_name,
                        clean_err,
                    )
                elif (
                    isinstance(err, ProviderAuthenticationError)
                    or "401" in str(err)
                    or "UNAUTHENTICATED" in str(err)
                    or "ACCESS_TOKEN_TYPE_UNSUPPORTED" in str(err)
                ):
                    self._tracker.record_auth_failed(candidate.name, cooldown_seconds=self._cooldown_seconds, error=clean_err)
                    attempted_errors.append(f"{candidate.name} (Auth Failed): {clean_err}")
                    if len(accumulated) > 0:
                        yield StreamError(error_message=f"Stream interrupted on {candidate.name}: {clean_err}", recoverable=False)
                        raise ProviderError(f"Stream interrupted on provider '{candidate.name}': {clean_err}") from err
                    self._logger.warning(
                        "[Provider] %s authentication failed (401) before emitting text. Marked as AUTH_FAILED (cooldown: %.0fs): %s. [Provider] Switching to next candidate...",
                        display_name,
                        self._cooldown_seconds,
                        clean_err,
                    )
                else:
                    self._tracker.record_failure(candidate.name, error=clean_err)
                    attempted_errors.append(f"{candidate.name}: {clean_err}")
                    if len(accumulated) > 0:
                        # Tokens were already dispatched to the consumer; cannot switch mid-sentence
                        yield StreamError(error_message=f"Stream interrupted on {candidate.name}: {clean_err}", recoverable=False)
                        raise ProviderError(f"Stream interrupted on provider '{candidate.name}': {clean_err}") from err

                    self._logger.warning(
                        "[Provider] %s failed before emitting text: %s. [Provider] Switching to next candidate...",
                        display_name,
                        clean_err,
                    )

        error_summary = "; ".join(attempted_errors)
        raise NoAvailableProviderError(f"All streaming providers failed: [{error_summary}]")
