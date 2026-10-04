"""Provider health tracking, failure classification, and status representations for LYRA."""

from dataclasses import dataclass
from enum import Enum
import time
from typing import Any

from lyra.core.exceptions import (
    ProviderAuthenticationError,
    ProviderError,
    ProviderQuotaExceededError,
    ProviderRateLimitError,
    ProviderTimeoutError,
)
from lyra.providers.base import AIProvider


class FailureCategory(str, Enum):
    """Normalized categories for AI provider failures."""

    SUCCESS = "SUCCESS"
    RATE_LIMITED = "RATE_LIMITED"
    QUOTA_EXHAUSTED = "QUOTA_EXHAUSTED"
    AUTHENTICATION_ERROR = "AUTHENTICATION_ERROR"
    NETWORK_ERROR = "NETWORK_ERROR"
    TIMEOUT = "TIMEOUT"
    MODEL_UNAVAILABLE = "MODEL_UNAVAILABLE"
    SERVICE_UNAVAILABLE = "SERVICE_UNAVAILABLE"
    INVALID_REQUEST = "INVALID_REQUEST"
    UNKNOWN_ERROR = "UNKNOWN_ERROR"


class ProviderHealthStatus(str, Enum):
    """Enumeration of provider health and availability states."""

    AVAILABLE = "AVAILABLE"
    DEGRADED = "DEGRADED"
    RATE_LIMITED = "RATE_LIMITED"
    QUOTA_EXHAUSTED = "QUOTA_EXHAUSTED"
    AUTH_FAILED = "AUTH_FAILED"
    OFFLINE = "OFFLINE"
    UNKNOWN = "UNKNOWN"
    NOT_CONFIGURED = "NOT_CONFIGURED"

    # Backward compatibility mappings
    TEMPORARILY_UNAVAILABLE = "TEMPORARILY_UNAVAILABLE"
    ERROR = "ERROR"
    UNAVAILABLE = "UNAVAILABLE"


def classify_failure(err: Exception) -> FailureCategory:
    """Classify an arbitrary exception into a normalized FailureCategory."""
    if isinstance(err, ProviderQuotaExceededError):
        return FailureCategory.QUOTA_EXHAUSTED
    if isinstance(err, ProviderRateLimitError):
        return FailureCategory.RATE_LIMITED
    if isinstance(err, ProviderAuthenticationError):
        return FailureCategory.AUTHENTICATION_ERROR
    if isinstance(err, ProviderTimeoutError):
        return FailureCategory.TIMEOUT

    err_str = str(err).upper()

    # Quota exhausted patterns
    if any(k in err_str for k in ("RESOURCE_EXHAUSTED", "FREE_TIER_REQUESTS", "QUOTA EXCEEDED", "QUOTA_EXHAUSTED", "QUOTA")):
        return FailureCategory.QUOTA_EXHAUSTED

    # Rate limited patterns
    if any(k in err_str for k in ("429", "RATE_LIMIT", "RATE LIMIT", "TOO MANY REQUESTS")):
        return FailureCategory.RATE_LIMITED

    # Authentication patterns
    if any(k in err_str for k in ("401", "403", "UNAUTHORIZED", "FORBIDDEN", "INVALID API KEY", "API_KEY_INVALID", "AUTH")):
        return FailureCategory.AUTHENTICATION_ERROR

    # Timeout patterns
    if any(k in err_str for k in ("TIMEOUT", "TIMED OUT", "DEADLINE EXCEEDED")):
        return FailureCategory.TIMEOUT

    # Network / connectivity patterns
    if any(k in err_str for k in ("CONNECTION REFUSED", "CANNOT CONNECT", "NETWORK", "GETADDRINFO FAILED", "URLERROR")):
        return FailureCategory.NETWORK_ERROR

    # Service availability patterns
    if any(k in err_str for k in ("503", "SERVICE UNAVAILABLE", "502", "BAD GATEWAY", "500", "INTERNAL SERVER ERROR")):
        return FailureCategory.SERVICE_UNAVAILABLE

    # Model unavailable patterns
    if any(k in err_str for k in ("404", "MODEL NOT FOUND", "DOES NOT EXIST", "NOT_FOUND")):
        return FailureCategory.MODEL_UNAVAILABLE

    # Invalid request patterns
    if any(k in err_str for k in ("400", "BAD REQUEST", "INVALID ARGUMENT", "VALIDATION")):
        return FailureCategory.INVALID_REQUEST

    return FailureCategory.UNKNOWN_ERROR


@dataclass
class HealthRecord:
    """Internal tracking record for a single provider's health and operational metrics."""

    status: ProviderHealthStatus = ProviderHealthStatus.AVAILABLE
    last_success: float | None = None
    last_failure: float | None = None
    last_error: str | None = None
    failure_category: FailureCategory | None = None
    consecutive_failures: int = 0
    cooldown_until: float = 0.0
    latency: float = 0.0

    @property
    def rate_limited_until(self) -> float:
        return self.cooldown_until

    @rate_limited_until.setter
    def rate_limited_until(self, val: float) -> None:
        self.cooldown_until = val


class ProviderHealthTracker:
    """Tracks, evaluates, and recovers operational health for all registered AI providers."""

    def __init__(self, default_cooldown_seconds: float = 300.0) -> None:
        self._default_cooldown = default_cooldown_seconds
        self._records: dict[str, HealthRecord] = {}

    def _get_or_create_record(self, provider_name: str) -> HealthRecord:
        norm = provider_name.lower().strip()
        if norm not in self._records:
            self._records[norm] = HealthRecord()
        return self._records[norm]

    def get_record(self, provider_name: str) -> HealthRecord:
        """Retrieve tracking record for a named provider."""
        return self._get_or_create_record(provider_name)

    def get_status(self, provider: AIProvider | str) -> ProviderHealthStatus:
        """Evaluate and return current health status of a provider with auto-recovery."""
        if isinstance(provider, str):
            record = self._get_or_create_record(provider)
        else:
            if not provider.is_configured:
                return ProviderHealthStatus.NOT_CONFIGURED
            record = self._get_or_create_record(provider.name)

        # Check if rate-limit, quota, or temporary cooldown has elapsed -> Auto-Recover!
        if record.status in (
            ProviderHealthStatus.QUOTA_EXHAUSTED,
            ProviderHealthStatus.RATE_LIMITED,
            ProviderHealthStatus.TEMPORARILY_UNAVAILABLE,
            ProviderHealthStatus.AUTH_FAILED,
            ProviderHealthStatus.DEGRADED,
            ProviderHealthStatus.ERROR,
            ProviderHealthStatus.UNAVAILABLE,
        ):
            if record.cooldown_until > 0.0:
                now = time.monotonic()
                if now >= record.cooldown_until:
                    # Cooldown window expired -> automatically restore to AVAILABLE!
                    record.status = ProviderHealthStatus.AVAILABLE
                    record.cooldown_until = 0.0
                    record.last_error = None
                    record.failure_category = None
                    record.consecutive_failures = 0
                    return ProviderHealthStatus.AVAILABLE
                return record.status

        return record.status

    def record_success(self, provider_name: str, latency: float = 0.0) -> None:
        """Mark provider as healthy following a successful generation."""
        record = self._get_or_create_record(provider_name)
        record.status = ProviderHealthStatus.AVAILABLE
        record.consecutive_failures = 0
        record.last_error = None
        record.failure_category = FailureCategory.SUCCESS
        record.cooldown_until = 0.0
        record.last_success = time.time()
        record.latency = latency

    def record_quota_exhausted(
        self,
        provider_name: str,
        cooldown_seconds: float | None = None,
        error: str | None = None,
    ) -> None:
        """Mark provider as quota exhausted with an active cooldown window."""
        record = self._get_or_create_record(provider_name)
        record.status = ProviderHealthStatus.QUOTA_EXHAUSTED
        record.failure_category = FailureCategory.QUOTA_EXHAUSTED
        record.last_error = error
        record.last_failure = time.time()
        record.consecutive_failures += 1
        cooldown = cooldown_seconds if cooldown_seconds is not None else self._default_cooldown
        record.cooldown_until = time.monotonic() + cooldown

    def record_rate_limited(
        self,
        provider_name: str,
        cooldown_seconds: float | None = None,
        error: str | None = None,
    ) -> None:
        """Mark provider as rate-limited with an active cooldown window."""
        record = self._get_or_create_record(provider_name)
        record.status = ProviderHealthStatus.RATE_LIMITED
        record.failure_category = FailureCategory.RATE_LIMITED
        record.last_error = error
        record.last_failure = time.time()
        record.consecutive_failures += 1
        cooldown = cooldown_seconds if cooldown_seconds is not None else self._default_cooldown
        record.cooldown_until = time.monotonic() + cooldown

    def record_auth_failed(
        self,
        provider_name: str,
        cooldown_seconds: float | None = None,
        error: str | None = None,
    ) -> None:
        """Mark provider as having failed authentication with an active cooldown window."""
        record = self._get_or_create_record(provider_name)
        record.status = ProviderHealthStatus.AUTH_FAILED
        record.failure_category = FailureCategory.AUTHENTICATION_ERROR
        record.last_error = error
        record.last_failure = time.time()
        record.consecutive_failures += 1
        cooldown = cooldown_seconds if cooldown_seconds is not None else self._default_cooldown
        record.cooldown_until = time.monotonic() + cooldown

    def record_temporarily_unavailable(
        self,
        provider_name: str,
        cooldown_seconds: float | None = None,
        error: str | None = None,
    ) -> None:
        """Mark provider as temporarily unavailable with an active cooldown window."""
        record = self._get_or_create_record(provider_name)
        record.status = ProviderHealthStatus.TEMPORARILY_UNAVAILABLE
        record.failure_category = FailureCategory.SERVICE_UNAVAILABLE
        record.last_error = error
        record.last_failure = time.time()
        record.consecutive_failures += 1
        cooldown = cooldown_seconds if cooldown_seconds is not None else self._default_cooldown
        record.cooldown_until = time.monotonic() + cooldown

    def record_error(
        self,
        provider_name: str,
        error: str | None = None,
    ) -> None:
        """Mark provider as in an error state following an operational failure."""
        record = self._get_or_create_record(provider_name)
        record.status = ProviderHealthStatus.ERROR
        record.failure_category = FailureCategory.UNKNOWN_ERROR
        record.last_error = error
        record.last_failure = time.time()
        record.consecutive_failures += 1

    def record_failure(
        self,
        provider_name: str,
        error: str | None = None,
        status: ProviderHealthStatus = ProviderHealthStatus.UNAVAILABLE,
        category: FailureCategory | None = None,
    ) -> None:
        """Mark provider as unavailable or in error following an operational failure."""
        record = self._get_or_create_record(provider_name)
        record.status = status
        record.failure_category = category or FailureCategory.UNKNOWN_ERROR
        record.last_error = error
        record.last_failure = time.time()
        record.consecutive_failures += 1

    def simulate_failure(
        self,
        provider_name: str,
        category: FailureCategory = FailureCategory.QUOTA_EXHAUSTED,
        cooldown_seconds: float = 300.0,
        error: str = "Simulated provider failure",
    ) -> None:
        """Simulate a provider failure for testing and resilience verification."""
        if category == FailureCategory.QUOTA_EXHAUSTED:
            self.record_quota_exhausted(provider_name, cooldown_seconds=cooldown_seconds, error=error)
        elif category == FailureCategory.RATE_LIMITED:
            self.record_rate_limited(provider_name, cooldown_seconds=cooldown_seconds, error=error)
        elif category == FailureCategory.AUTHENTICATION_ERROR:
            self.record_auth_failed(provider_name, cooldown_seconds=cooldown_seconds, error=error)
        else:
            self.record_temporarily_unavailable(provider_name, cooldown_seconds=cooldown_seconds, error=error)

    def reset(self, provider_name: str | None = None) -> None:
        """Reset health records for one or all providers."""
        if provider_name:
            self._records.pop(provider_name.lower().strip(), None)
        else:
            self._records.clear()
