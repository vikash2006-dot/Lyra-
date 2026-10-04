"""Unit tests for Microphone audio capture."""

import asyncio
from unittest.mock import MagicMock, patch
import pytest
import speech_recognition as sr

from lyra.config.settings import Settings
from lyra.core.exceptions import (
    EmptyAudioError,
    MicrophoneUnavailableError,
    SilenceTimeoutError,
)
from lyra.voice.capture import MicrophoneCapture


def test_microphone_capture_from_settings() -> None:
    """Verify initialization from application settings."""
    settings = Settings(
        voice_silence_duration_seconds=1.5,
        voice_input_timeout_seconds=20.0,
    )
    capture = MicrophoneCapture.from_settings(settings)
    assert capture.pause_threshold == 1.5
    assert capture.phrase_time_limit == 20.0


def test_capture_turn_sync_silence_timeout() -> None:
    """Verify that capture_turn_sync raises SilenceTimeoutError on timeout."""
    mock_recognizer = MagicMock()
    mock_recognizer.listen.side_effect = sr.WaitTimeoutError("Timed out")
    mock_source = MagicMock()
    mock_factory = MagicMock()
    mock_factory.return_value.__enter__.return_value = mock_source
    mock_factory.return_value.__exit__.return_value = None

    capture = MicrophoneCapture(
        recognizer=mock_recognizer,
        microphone_factory=mock_factory,
    )

    with pytest.raises(SilenceTimeoutError):
        capture.capture_turn_sync(timeout=2.0)


def test_capture_turn_sync_success() -> None:
    """Verify that capture_turn_sync returns valid WAV bytes on successful audio capture."""
    mock_audio = MagicMock()
    # Dummy valid 44-byte RIFF wav header + 10 bytes
    dummy_wav = b"RIFF" + b"\x00" * 40 + b"DATA"
    mock_audio.get_wav_data.return_value = dummy_wav

    mock_recognizer = MagicMock()
    mock_recognizer.listen.return_value = mock_audio
    mock_source = MagicMock()
    mock_factory = MagicMock()
    mock_factory.return_value.__enter__.return_value = mock_source
    mock_factory.return_value.__exit__.return_value = None

    capture = MicrophoneCapture(
        recognizer=mock_recognizer,
        microphone_factory=mock_factory,
    )

    wav_result = capture.capture_turn_sync(timeout=5.0)
    assert wav_result == dummy_wav


def test_capture_turn_sync_empty_audio() -> None:
    """Verify that capture_turn_sync raises EmptyAudioError when payload is too small."""
    mock_audio = MagicMock()
    mock_audio.get_wav_data.return_value = b"short"

    mock_recognizer = MagicMock()
    mock_recognizer.listen.return_value = mock_audio
    mock_source = MagicMock()
    mock_factory = MagicMock()
    mock_factory.return_value.__enter__.return_value = mock_source
    mock_factory.return_value.__exit__.return_value = None

    capture = MicrophoneCapture(
        recognizer=mock_recognizer,
        microphone_factory=mock_factory,
    )

    with pytest.raises(EmptyAudioError):
        capture.capture_turn_sync(timeout=5.0)


def test_capture_turn_sync_device_unavailable() -> None:
    """Verify that OSError when accessing mic raises MicrophoneUnavailableError."""
    mock_factory = MagicMock(side_effect=OSError("Device not found"))

    capture = MicrophoneCapture(
        microphone_factory=mock_factory,
    )

    with pytest.raises(MicrophoneUnavailableError):
        capture.capture_turn_sync()


def test_capture_turn_async() -> None:
    """Verify async capture_turn invokes capture_turn_sync in worker thread."""
    async def _run():
        capture = MicrophoneCapture()
        dummy_wav = b"RIFF" + b"\x00" * 40 + b"DATA"

        with patch.object(capture, "capture_turn_sync", return_value=dummy_wav) as mock_sync:
            result = await capture.capture_turn(timeout=5.0)

        assert result == dummy_wav
        mock_sync.assert_called_once_with(timeout=5.0)

    asyncio.run(_run())
