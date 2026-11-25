"""Decoupled Voice Pipeline connecting speech audio to LYRA's CompanionOrchestrator."""

import asyncio
from typing import AsyncIterable

from lyra.companion.orchestrator import CompanionOrchestrator
from lyra.companion.session import Session
from lyra.core.exceptions import (
    VoiceError,
    VoiceExecutionError,
    VoiceInterruptedError,
    VoiceNotConfiguredError,
)
from lyra.observability.logging import get_logger
from lyra.voice.base import SpeechToTextProvider, TextToSpeechProvider
from lyra.voice.models import AudioChunk, CancellationToken, TranscriptionResult


class VoicePipeline:
    """Manages audio input, speech transcription, companion turn processing, and audio output."""

    def __init__(
        self,
        orchestrator: CompanionOrchestrator,
        stt_provider: SpeechToTextProvider | None = None,
        tts_provider: TextToSpeechProvider | None = None,
        timeout_seconds: float = 20.0,
    ) -> None:
        self.orchestrator: CompanionOrchestrator = orchestrator
        self.stt_provider: SpeechToTextProvider | None = stt_provider
        self.tts_provider: TextToSpeechProvider | None = tts_provider
        self.timeout_seconds: float = timeout_seconds
        self._active_token: CancellationToken = CancellationToken()
        self._logger = get_logger("voice.pipeline")

    def interrupt(self) -> None:
        """Interrupt active speech synthesis or streaming output immediately."""
        self._logger.info("Voice interruption signaled; cancelling active token")
        self._active_token.cancel()

    def reset_cancellation_token(self) -> CancellationToken:
        """Reset the cancellation token for a new conversational turn."""
        self._active_token = CancellationToken()
        return self._active_token

    async def transcribe_audio(self, audio_data: bytes, mime_type: str = "audio/wav") -> str:
        """Transcribe raw audio bytes using the configured STT provider."""
        if not self.stt_provider:
            raise VoiceNotConfiguredError("No SpeechToTextProvider is configured.")
        if not self.stt_provider.is_configured:
            raise VoiceNotConfiguredError(f"STT provider '{self.stt_provider.name}' is not configured.")

        res: TranscriptionResult = await asyncio.wait_for(
            self.stt_provider.transcribe(audio_data, mime_type=mime_type),
            timeout=self.timeout_seconds,
        )
        return res.text

    async def synthesize_response_stream(
        self,
        text: str,
        voice: str | None = None,
        cancellation_token: CancellationToken | None = None,
    ) -> AsyncIterable[AudioChunk]:
        """Stream synthesized audio chunks for response text."""
        token = cancellation_token or self._active_token

        if not self.tts_provider or not self.tts_provider.is_configured:
            self._logger.debug("TTS provider not configured; returning empty audio stream")
            yield AudioChunk(data=b"", mime_type="audio/wav", is_final=True)
            return

        try:
            async for chunk in self.tts_provider.synthesize_stream(
                text=text,
                voice=voice,
                cancellation_token=token,
            ):
                yield chunk
        except VoiceInterruptedError:
            self._logger.info("Voice synthesis stream cleanly interrupted")
            yield AudioChunk(data=b"", mime_type="audio/wav", is_final=True)
        except Exception as err:
            self._logger.error("TTS streaming failed: %s", err)
            yield AudioChunk(data=b"", mime_type="audio/wav", is_final=True)

    async def process_audio_turn(
        self,
        session: Session,
        audio_data: bytes,
        voice: str | None = None,
    ) -> tuple[str, AsyncIterable[AudioChunk]]:
        """Process a complete voice turn:

        Audio In -> STT -> Orchestrator -> Response Text -> TTS Stream Out

        Args:
            session: Active conversation Session.
            audio_data: Input speech audio bytes.
            voice: Optional target voice identifier.

        Returns:
            Tuple of (assistant_reply_text, audio_chunk_stream).
        """
        # Cancel any previous speaking turn before beginning a new turn
        self.interrupt()
        token = self.reset_cancellation_token()

        # 1. Transcribe audio to text
        try:
            user_text = await self.transcribe_audio(audio_data)
        except Exception as stt_err:
            self._logger.error("Audio transcription failed: %s", stt_err)
            raise VoiceExecutionError(f"Transcription failed: {stt_err}") from stt_err

        if not user_text.strip():
            self._logger.warning("Empty transcription received from STT")
            async def _empty_stream() -> AsyncIterable[AudioChunk]:
                yield AudioChunk(data=b"", mime_type="audio/wav", is_final=True)
            return "", _empty_stream()

        # 2. Process turn through companion orchestrator
        reply_text = await self.orchestrator.process_turn(session, user_text)

        # 3. Synthesize reply text into streaming audio
        audio_stream = self.synthesize_response_stream(
            text=reply_text,
            voice=voice,
            cancellation_token=token,
        )

        return reply_text, audio_stream
