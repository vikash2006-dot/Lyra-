"""Unit tests for FreeSTTProvider using Google Web Speech API."""

import asyncio
from unittest.mock import MagicMock, patch
import pytest
import speech_recognition as sr

from lyra.core.exceptions import VoiceExecutionError
from lyra.voice.models import TranscriptionResult
from lyra.voice.providers.free_stt import FreeSTTProvider


def test_free_stt_properties() -> None:
    """Verify FreeSTTProvider name, language, and configuration status."""
    provider = FreeSTTProvider(language="en-US")
    assert provider.name == "free_stt"
    assert provider.language == "en-US"
    assert provider.is_configured is True


def test_free_stt_transcribe_empty_bytes() -> None:
    """Verify that empty or tiny audio bytes return empty TranscriptionResult."""
    provider = FreeSTTProvider()
    result = provider.transcribe_sync(b"")
    assert result.text == ""
    assert result.confidence == 0.0


def test_free_stt_transcribe_sync_success() -> None:
    """Verify successful speech recognition returns transcription text."""
    mock_recognizer = MagicMock()
    mock_recognizer.recognize_google.return_value = "Hello Lyra"

    provider = FreeSTTProvider(recognizer=mock_recognizer)
    dummy_wav = b"RIFF" + b"\x00" * 40 + b"DATA"

    with patch("speech_recognition.AudioFile"):
        result = provider.transcribe_sync(dummy_wav)

    assert result.text == "Hello Lyra"
    assert result.confidence > 0.0


def test_free_stt_transcribe_unintelligible() -> None:
    """Verify that UnknownValueError returns an empty string without raising an exception."""
    mock_recognizer = MagicMock()
    mock_recognizer.recognize_google.side_effect = sr.UnknownValueError()

    provider = FreeSTTProvider(recognizer=mock_recognizer)
    dummy_wav = b"RIFF" + b"\x00" * 40 + b"DATA"

    with patch("speech_recognition.AudioFile"):
        result = provider.transcribe_sync(dummy_wav)

    assert result.text == ""
    assert result.confidence == 0.0


def test_free_stt_transcribe_request_error() -> None:
    """Verify that network/API RequestError raises VoiceExecutionError."""
    mock_recognizer = MagicMock()
    mock_recognizer.recognize_google.side_effect = sr.RequestError("Network unreachable")

    provider = FreeSTTProvider(recognizer=mock_recognizer)
    dummy_wav = b"RIFF" + b"\x00" * 40 + b"DATA"

    with patch("speech_recognition.AudioFile"):
        with pytest.raises(VoiceExecutionError) as exc_info:
            provider.transcribe_sync(dummy_wav)

    assert "Network unreachable" in str(exc_info.value)


def test_free_stt_transcribe_async() -> None:
    """Verify async transcribe calls transcribe_sync in worker thread."""
    async def _run():
        provider = FreeSTTProvider()
        expected = TranscriptionResult(text="Async speech", confidence=0.9, language="en-US")

        with patch.object(provider, "transcribe_sync", return_value=expected) as mock_sync:
            result = await provider.transcribe(b"dummy_wav")

        assert result.text == "Async speech"
        mock_sync.assert_called_once()

    asyncio.run(_run())
