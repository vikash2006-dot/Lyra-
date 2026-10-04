"""Microphone audio capture implementation for LYRA voice interaction."""

import asyncio
import io
from typing import Any

from lyra.config.settings import Settings, load_settings
from lyra.core.exceptions import (
    EmptyAudioError,
    MicrophoneUnavailableError,
    SilenceTimeoutError,
    VoiceExecutionError,
)
from lyra.observability.logging import get_logger

logger = get_logger("voice.capture")


class MicrophoneCapture:
    """Captures speech audio from the microphone with voice activity and silence detection."""

    def __init__(
        self,
        energy_threshold: float = 300.0,
        pause_threshold: float = 1.0,
        phrase_time_limit: float | None = 15.0,
        device_index: int | None = None,
        recognizer: Any | None = None,
        microphone_factory: Any | None = None,
    ) -> None:
        self.energy_threshold = energy_threshold
        self.pause_threshold = pause_threshold
        self.phrase_time_limit = phrase_time_limit
        self.device_index = device_index
        self._recognizer = recognizer
        self._microphone_factory = microphone_factory

    @classmethod
    def from_settings(cls, settings: Settings | None = None) -> "MicrophoneCapture":
        """Construct MicrophoneCapture using active configuration settings."""
        s = settings or load_settings()
        return cls(
            pause_threshold=s.voice_silence_duration_seconds,
            phrase_time_limit=s.voice_input_timeout_seconds,
        )

    def _get_recognizer(self) -> Any:
        if self._recognizer is not None:
            return self._recognizer
        try:
            import speech_recognition as sr

            r = sr.Recognizer()
            r.energy_threshold = self.energy_threshold
            r.dynamic_energy_threshold = True
            r.pause_threshold = self.pause_threshold
            return r
        except ImportError as err:
            raise MicrophoneUnavailableError(
                "SpeechRecognition package is not installed. Install with: pip install SpeechRecognition"
            ) from err

    def _get_microphone(self) -> Any:
        if self._microphone_factory is not None:
            return self._microphone_factory()
        try:
            import speech_recognition as sr

            return sr.Microphone(device_index=self.device_index)
        except (ImportError, OSError, AttributeError) as err:
            raise MicrophoneUnavailableError(
                f"Microphone is unavailable or access was denied by OS: {err}"
            ) from err

    def capture_turn_sync(self, timeout: float | None = 10.0) -> bytes:
        """Synchronously capture audio from microphone until user stops speaking."""
        import speech_recognition as sr

        recognizer = self._get_recognizer()
        try:
            with self._get_microphone() as source:
                # Adjust for ambient noise briefly if dynamic threshold enabled
                try:
                    recognizer.adjust_for_ambient_noise(source, duration=0.2)
                except Exception as noise_err:
                    logger.debug("Ambient noise adjustment notice: %s", noise_err)

                logger.debug("Listening for microphone input (timeout=%s)...", timeout)
                audio = recognizer.listen(
                    source,
                    timeout=timeout,
                    phrase_time_limit=self.phrase_time_limit,
                )
        except sr.WaitTimeoutError as timeout_err:
            raise SilenceTimeoutError("No speech detected within the timeout window.") from timeout_err
        except (OSError, PermissionError, AttributeError) as os_err:
            raise MicrophoneUnavailableError(
                f"Cannot access microphone device: {os_err}"
            ) from os_err
        except Exception as err:
            raise VoiceExecutionError(f"Microphone capture error: {err}") from err

        if audio is None:
            raise EmptyAudioError("Captured audio object is null.")

        wav_data = audio.get_wav_data()
        if not wav_data or len(wav_data) < 44:  # 44 bytes is standard WAV header size
            raise EmptyAudioError("Captured audio payload is empty or corrupt.")

        return wav_data

    async def capture_turn(self, timeout: float | None = 10.0) -> bytes:
        """Asynchronously capture audio from microphone in a worker thread."""
        return await asyncio.to_thread(self.capture_turn_sync, timeout=timeout)
