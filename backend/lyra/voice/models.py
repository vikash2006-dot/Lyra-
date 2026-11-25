"""Canonical domain models and cancellation primitives for LYRA Voice."""

from dataclasses import dataclass, field
import threading
from typing import Callable

from lyra.core.exceptions import VoiceInterruptedError


@dataclass(frozen=True)
class AudioChunk:
    """Canonical model for a single audio chunk in streaming or batch synthesis."""

    data: bytes
    mime_type: str = "audio/mpeg"
    sample_rate: int = 24000
    is_final: bool = False

    def __len__(self) -> int:
        return len(self.data)


@dataclass(frozen=True)
class TranscriptionResult:
    """Canonical model for speech-to-text transcription output."""

    text: str
    confidence: float | None = None
    language: str | None = None


class CancellationToken:
    """Thread-safe cancellation token for interrupting ongoing voice synthesis or playback."""

    def __init__(self) -> None:
        self._cancelled = threading.Event()
        self._callbacks: list[Callable[[], None]] = []
        self._lock = threading.Lock()

    def cancel(self) -> None:
        """Signal cancellation and trigger all registered interruption callbacks."""
        with self._lock:
            if not self._cancelled.is_set():
                self._cancelled.set()
                for cb in self._callbacks:
                    try:
                        cb()
                    except Exception:  # pylint: disable=broad-except
                        pass

    @property
    def is_cancelled(self) -> bool:
        """Return True if cancellation has been requested."""
        return self._cancelled.is_set()

    def check_cancelled(self) -> None:
        """Raise VoiceInterruptedError if cancellation was signaled."""
        if self.is_cancelled:
            raise VoiceInterruptedError("Voice operation was interrupted by user or cancellation token.")

    def add_callback(self, callback: Callable[[], None]) -> None:
        """Register a callback to be invoked immediately upon cancellation."""
        with self._lock:
            if self.is_cancelled:
                try:
                    callback()
                except Exception:
                    pass
            else:
                self._callbacks.append(callback)
