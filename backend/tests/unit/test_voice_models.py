"""Unit tests for LYRA Voice models and cancellation primitives."""

import pytest

from lyra.core.exceptions import VoiceInterruptedError
from lyra.voice.models import AudioChunk, CancellationToken, TranscriptionResult


def test_audio_chunk_properties():
    """Verify AudioChunk fields and length method."""
    chunk = AudioChunk(data=b"test_audio_data", mime_type="audio/mpeg", sample_rate=24000, is_final=False)
    assert chunk.data == b"test_audio_data"
    assert chunk.mime_type == "audio/mpeg"
    assert chunk.sample_rate == 24000
    assert chunk.is_final is False
    assert len(chunk) == len(b"test_audio_data")


def test_transcription_result_properties():
    """Verify TranscriptionResult fields."""
    res = TranscriptionResult(text="Hello world", confidence=0.98, language="en")
    assert res.text == "Hello world"
    assert res.confidence == 0.98
    assert res.language == "en"


def test_cancellation_token_lifecycle():
    """Verify CancellationToken states, callbacks, and exception checks."""
    token = CancellationToken()
    assert token.is_cancelled is False

    # check_cancelled does not raise when not cancelled
    token.check_cancelled()

    # Track callback invocation
    called = []
    token.add_callback(lambda: called.append(True))
    assert not called

    # Signal cancellation
    token.cancel()
    assert token.is_cancelled is True
    assert called == [True]

    # Calling check_cancelled now raises VoiceInterruptedError
    with pytest.raises(VoiceInterruptedError, match="interrupted"):
        token.check_cancelled()

    # Adding a callback after already cancelled runs immediately
    late_called = []
    token.add_callback(lambda: late_called.append("late"))
    assert late_called == ["late"]
