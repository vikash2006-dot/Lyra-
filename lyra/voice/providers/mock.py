"""Mock STT and TTS providers for deterministic testing and headless runs."""

import asyncio
from typing import AsyncIterable

from lyra.voice.base import SpeechToTextProvider, TextToSpeechProvider
from lyra.voice.models import AudioChunk, CancellationToken, TranscriptionResult


class MockSTTProvider(SpeechToTextProvider):
    """Deterministic Speech-to-Text provider for tests."""

    def __init__(self, fixed_text: str = "Hello LYRA, what time is it?", is_configured: bool = True) -> None:
        self.fixed_text = fixed_text
        self._configured = is_configured

    @property
    def name(self) -> str:
        return "mock_stt"

    @property
    def is_configured(self) -> bool:
        return self._configured

    def set_transcription_text(self, text: str) -> None:
        """Update deterministic text to be returned by transcribe()."""
        self.fixed_text = text

    async def transcribe(
        self,
        audio_data: bytes,
        mime_type: str = "audio/wav",
        timeout: float | None = None,
    ) -> TranscriptionResult:
        if not audio_data:
            return TranscriptionResult(text="", confidence=0.0)
        return TranscriptionResult(text=self.fixed_text, confidence=0.99, language="en")


class MockTTSProvider(TextToSpeechProvider):
    """Deterministic Text-to-Speech provider for tests with streaming & interruption hooks."""

    def __init__(self, is_configured: bool = True, chunk_delay: float = 0.01) -> None:
        self._configured = is_configured
        self.chunk_delay = chunk_delay
        self.synthesize_call_count = 0

    @property
    def name(self) -> str:
        return "mock_tts"

    @property
    def is_configured(self) -> bool:
        return self._configured

    async def synthesize(
        self,
        text: str,
        voice: str | None = None,
        cancellation_token: CancellationToken | None = None,
    ) -> AudioChunk:
        self.synthesize_call_count += 1
        if cancellation_token:
            cancellation_token.check_cancelled()
        return AudioChunk(
            data=f"MOCK_AUDIO({text})".encode("utf-8"),
            mime_type="audio/wav",
            is_final=True,
        )

    async def synthesize_stream(
        self,
        text: str,
        voice: str | None = None,
        cancellation_token: CancellationToken | None = None,
    ) -> AsyncIterable[AudioChunk]:
        self.synthesize_call_count += 1
        chunks = [b"CHUNK_1", b"CHUNK_2", b"CHUNK_3"]
        for chunk in chunks:
            if cancellation_token:
                cancellation_token.check_cancelled()
            if self.chunk_delay > 0:
                await asyncio.sleep(self.chunk_delay)
            if cancellation_token:
                cancellation_token.check_cancelled()
            yield AudioChunk(data=chunk, mime_type="audio/wav", is_final=False)

        yield AudioChunk(data=b"", mime_type="audio/wav", is_final=True)
