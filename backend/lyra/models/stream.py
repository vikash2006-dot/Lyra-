"""Streaming events and chunk models for incremental response generation in LYRA."""

from abc import ABC
from dataclasses import dataclass, field
import threading
import time
from typing import Any

from lyra.core.exceptions import ModelValidationError, StreamInterruptedError
from lyra.models.messages import Usage


class CancellationToken:
    """Thread-safe cooperative cancellation token for in-progress operations."""

    def __init__(self) -> None:
        self._cancelled = threading.Event()
        self._reason: str | None = None

    def cancel(self, reason: str = "Operation cancelled by user.") -> None:
        """Flag the operation as cancelled."""
        self._reason = reason
        self._cancelled.set()

    @property
    def is_cancelled(self) -> bool:
        """True if cancellation has been requested."""
        return self._cancelled.is_set()

    @property
    def reason(self) -> str | None:
        """Reason provided for cancellation."""
        return self._reason

    def check_cancelled(self) -> None:
        """Raise StreamInterruptedError if cancellation was requested."""
        if self.is_cancelled:
            raise StreamInterruptedError(self._reason or "Stream cancelled.")


@dataclass(frozen=True)
class StreamEvent(ABC):
    """Base class for all provider-independent stream events."""

    timestamp: float = field(default_factory=time.time)
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class StreamStarted(StreamEvent):
    """Emitted when an AI provider starts generating tokens."""

    provider: str = ""
    model: str = ""

    def __post_init__(self) -> None:
        if not self.provider:
            raise ModelValidationError("StreamStarted requires a non-empty provider identifier.")


@dataclass(frozen=True)
class TextDelta(StreamEvent):
    """Incremental text token received from a streaming provider."""

    delta: str = ""
    index: int = 0

    def __post_init__(self) -> None:
        if not isinstance(self.delta, str):
            raise ModelValidationError("TextDelta delta must be a string.")


@dataclass(frozen=True)
class StreamCompleted(StreamEvent):
    """Emitted when the provider finishes response generation."""

    full_text: str = ""
    finish_reason: str | None = None
    usage: Usage | None = None


@dataclass(frozen=True)
class StreamError(StreamEvent):
    """Emitted when an unrecoverable streaming failure occurs."""

    error_message: str = ""
    error_code: str | None = None
    recoverable: bool = False

    def __post_init__(self) -> None:
        if not self.error_message:
            raise ModelValidationError("StreamError requires an error_message.")


@dataclass(frozen=True)
class StreamChunk:
    """Legacy/convenience representation of a streaming delta."""

    delta: str
    model: str
    finish_reason: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not isinstance(self.delta, str):
            raise ModelValidationError("StreamChunk delta must be a string.")
        if not self.model or not isinstance(self.model, str):
            raise ModelValidationError("StreamChunk model must be a non-empty string.")
