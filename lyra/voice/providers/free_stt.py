"""Free, zero-cost Speech-to-Text provider implementation for LYRA voice interaction."""

import asyncio
import io
from typing import Any

from lyra.core.exceptions import (
    VoiceExecutionError,
    VoiceNotConfiguredError,
    VoiceTimeoutError,
)
from lyra.observability.logging import get_logger
from lyra.voice.base import SpeechToTextProvider
from lyra.voice.models import TranscriptionResult

logger = get_logger("voice.stt.free")


class FreeSTTProvider(SpeechToTextProvider):
    """Free Speech-to-Text provider using Google's public speech recognition service (zero API keys)."""

    def __init__(self, language: str = "en-US", recognizer: Any | None = None) -> None:
        self.language = language
        self._recognizer = recognizer

    @property
    def name(self) -> str:
        return "free_stt"

    @property
    def is_configured(self) -> bool:
        """Free STT is always configured and requires zero API keys."""
        return True

    def _get_recognizer(self) -> Any:
        if self._recognizer is not None:
            return self._recognizer
        try:
            import speech_recognition as sr
            return sr.Recognizer()
        except ImportError as err:
            raise VoiceNotConfiguredError(
                "SpeechRecognition package is not installed."
            ) from err

    def transcribe_sync(
        self,
        audio_data: bytes,
        mime_type: str = "audio/wav",
        timeout: float | None = None,
    ) -> TranscriptionResult:
        """Synchronously transcribe WAV audio bytes into text."""
        if not audio_data or len(audio_data) < 44:
            return TranscriptionResult(text="", confidence=0.0, language=self.language)

        try:
            import speech_recognition as sr
        except ImportError as err:
            raise VoiceNotConfiguredError(
                "SpeechRecognition package is not installed."
            ) from err

        recognizer = self._get_recognizer()

        try:
            # Read WAV bytes into an AudioFile reader
            with io.BytesIO(audio_data) as audio_file:
                with sr.AudioFile(audio_file) as source:
                    audio_obj = recognizer.record(source)

            # Recognize speech using Google's free public endpoint
            text = recognizer.recognize_google(audio_obj, language=self.language)
            cleaned = text.strip()
            logger.debug("Free STT recognized: '%s'", cleaned)
            return TranscriptionResult(text=cleaned, confidence=0.95, language=self.language)
        except sr.UnknownValueError:
            # Speech was unintelligible or silent
            logger.debug("Speech was unintelligible to STT")
            return TranscriptionResult(text="", confidence=0.0, language=self.language)
        except sr.RequestError as req_err:
            logger.warning("Free STT recognition service error: %s", req_err)
            raise VoiceExecutionError(
                f"Free STT recognition service error: {req_err}"
            ) from req_err
        except Exception as err:
            logger.warning("STT transcription failed: %s", err)
            raise VoiceExecutionError(f"STT transcription failed: {err}") from err

    async def transcribe(
        self,
        audio_data: bytes,
        mime_type: str = "audio/wav",
        timeout: float | None = None,
    ) -> TranscriptionResult:
        """Asynchronously transcribe audio bytes in a worker thread."""
        return await asyncio.to_thread(
            self.transcribe_sync,
            audio_data=audio_data,
            mime_type=mime_type,
            timeout=timeout,
        )
