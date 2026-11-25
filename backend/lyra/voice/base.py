"""Abstract base interfaces for Speech-to-Text and Text-to-Speech providers."""

from abc import ABC, abstractmethod
from typing import AsyncIterable

from lyra.voice.models import AudioChunk, CancellationToken, TranscriptionResult


class SpeechToTextProvider(ABC):
    """Abstract base provider interface for Speech-to-Text (transcription)."""

    @property
    @abstractmethod
    def name(self) -> str:
        """Provider identifier name."""

    @property
    @abstractmethod
    def is_configured(self) -> bool:
        """Return True if credentials and dependencies are properly configured."""

    @abstractmethod
    async def transcribe(
        self,
        audio_data: bytes,
        mime_type: str = "audio/wav",
        timeout: float | None = None,
    ) -> TranscriptionResult:
        """Transcribe audio bytes into text.

        Args:
            audio_data: Binary audio payload.
            mime_type: Audio encoding/container format (e.g. 'audio/wav', 'audio/mpeg').
            timeout: Optional custom timeout in seconds.

        Returns:
            TranscriptionResult containing transcribed text.
        """

    async def transcribe_stream(
        self,
        audio_stream: AsyncIterable[bytes],
        mime_type: str = "audio/wav",
    ) -> AsyncIterable[TranscriptionResult]:
        """Transcribe an incoming stream of audio bytes.

        Default base implementation accumulates stream bytes and yields final result.
        """
        buffer = bytearray()
        async for chunk in audio_stream:
            buffer.extend(chunk)
        if buffer:
            result = await self.transcribe(bytes(buffer), mime_type=mime_type)
            yield result


class TextToSpeechProvider(ABC):
    """Abstract base provider interface for Text-to-Speech (synthesis)."""

    @property
    @abstractmethod
    def name(self) -> str:
        """Provider identifier name."""

    @property
    @abstractmethod
    def is_configured(self) -> bool:
        """Return True if credentials and dependencies are properly configured."""

    @abstractmethod
    async def synthesize(
        self,
        text: str,
        voice: str | None = None,
        cancellation_token: CancellationToken | None = None,
    ) -> AudioChunk:
        """Synthesize text into complete audio bytes.

        Args:
            text: Text to synthesize.
            voice: Optional voice ID or voice name.
            cancellation_token: Optional token to interrupt/cancel synthesis.

        Returns:
            AudioChunk containing synthesized audio bytes.
        """

    @abstractmethod
    async def synthesize_stream(
        self,
        text: str,
        voice: str | None = None,
        cancellation_token: CancellationToken | None = None,
    ) -> AsyncIterable[AudioChunk]:
        """Stream synthesized audio chunks as they are generated.

        Args:
            text: Text to synthesize.
            voice: Optional voice ID or voice name.
            cancellation_token: Optional token to cancel synthesis mid-stream.

        Yields:
            AudioChunk instances representing progressive audio stream.
        """
