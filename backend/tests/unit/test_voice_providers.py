"""Unit tests for Voice providers (ElevenLabs, System, and Mock)."""

import asyncio
import io
import socket
from unittest.mock import MagicMock, patch
import urllib.error
import pytest

from lyra.core.exceptions import (
    VoiceAuthenticationError,
    VoiceExecutionError,
    VoiceInterruptedError,
    VoiceNotConfiguredError,
    VoiceRateLimitError,
    VoiceTimeoutError,
)
from lyra.voice.models import CancellationToken
from lyra.voice.providers.elevenlabs import ElevenLabsTTSProvider
from lyra.voice.providers.mock import MockSTTProvider, MockTTSProvider
from lyra.voice.providers.system import SystemTTSProvider


def make_mock_http_response(content: bytes) -> MagicMock:
    """Create a mock HTTP response context manager."""
    resp = MagicMock()
    resp.read.side_effect = [content, b""]  # First call returns content, subsequent returns EOF
    resp.__enter__.return_value = resp
    resp.__exit__.return_value = None
    return resp


def test_mock_stt_provider():
    """Verify MockSTTProvider transcription and stream."""
    stt = MockSTTProvider(fixed_text="Turn on lights", is_configured=True)
    assert stt.name == "mock_stt"
    assert stt.is_configured is True

    res = asyncio.run(stt.transcribe(b"dummy_audio_bytes"))
    assert res.text == "Turn on lights"
    assert res.confidence == 0.99

    empty_res = asyncio.run(stt.transcribe(b""))
    assert empty_res.text == ""

    # Stream transcription test
    async def _audio_stream():
        yield b"chunk1"
        yield b"chunk2"

    async def _collect_stream():
        results = []
        async for r in stt.transcribe_stream(_audio_stream()):
            results.append(r)
        return results

    stream_res = asyncio.run(_collect_stream())
    assert len(stream_res) == 1
    assert stream_res[0].text == "Turn on lights"


def test_mock_tts_provider_and_interruption():
    """Verify MockTTSProvider synthesis, streaming, and interruption handling."""
    tts = MockTTSProvider(chunk_delay=0.01)
    assert tts.name == "mock_tts"
    assert tts.is_configured is True

    chunk = asyncio.run(tts.synthesize("Hello world"))
    assert b"MOCK_AUDIO" in chunk.data

    # Stream all chunks
    async def _collect():
        collected = []
        async for c in tts.synthesize_stream("Testing stream"):
            collected.append(c.data)
        return collected

    chunks = asyncio.run(_collect())
    assert len(chunks) == 4  # 3 content chunks + 1 final empty chunk

    # Interruption test
    token = CancellationToken()

    async def _stream_with_interruption():
        collected = []
        async for c in tts.synthesize_stream("Interrupted speech", cancellation_token=token):
            collected.append(c.data)
            token.cancel()  # Cancel after first chunk
        return collected

    with pytest.raises(VoiceInterruptedError):
        asyncio.run(_stream_with_interruption())


def test_elevenlabs_unconfigured():
    """Verify ElevenLabsTTSProvider raises error when unconfigured."""
    tts = ElevenLabsTTSProvider(api_key=None)
    assert tts.is_configured is False

    with pytest.raises(VoiceNotConfiguredError, match="not configured"):
        asyncio.run(tts.synthesize("Hello"))


def test_elevenlabs_successful_synthesis():
    """Verify ElevenLabs synthesis with mocked HTTP response."""
    tts = ElevenLabsTTSProvider(api_key="el-test-key", default_voice_id="rachel")
    assert tts.is_configured is True

    mock_mp3 = b"ID3\x03\x00\x00\x00MP3_DATA"
    with patch("urllib.request.urlopen", return_value=make_mock_http_response(mock_mp3)):
        chunk = asyncio.run(tts.synthesize("Good morning LYRA"))

    assert chunk.data == mock_mp3
    assert chunk.mime_type == "audio/mpeg"


def test_elevenlabs_voice_id_parameter_alias():
    """Verify ElevenLabsTTSProvider accepts voice_id as alias for default_voice_id."""
    tts = ElevenLabsTTSProvider(api_key="el-test-key", voice_id="custom-alias-voice")
    assert tts._default_voice_id == "custom-alias-voice"


def test_elevenlabs_rate_limit_error():
    """Verify HTTP 429 raises VoiceRateLimitError."""
    tts = ElevenLabsTTSProvider(api_key="el-test-key")

    err = urllib.error.HTTPError(
        url="https://api.elevenlabs.io/v1/text-to-speech/voice",
        code=429,
        msg="Too Many Requests",
        hdrs={},  # type: ignore
        fp=io.BytesIO(b"Quota exceeded"),
    )

    with patch("urllib.request.urlopen", side_effect=err):
        with pytest.raises(VoiceRateLimitError, match="rate limit"):
            asyncio.run(tts.synthesize("Hello"))


def test_elevenlabs_auth_error():
    """Verify HTTP 401 raises VoiceAuthenticationError."""
    tts = ElevenLabsTTSProvider(api_key="invalid-key")

    err = urllib.error.HTTPError(
        url="https://api.elevenlabs.io/v1/text-to-speech/voice",
        code=401,
        msg="Unauthorized",
        hdrs={},  # type: ignore
        fp=io.BytesIO(b"Invalid API key"),
    )

    with patch("urllib.request.urlopen", side_effect=err):
        with pytest.raises(VoiceAuthenticationError, match="authentication failed"):
            asyncio.run(tts.synthesize("Hello"))


def test_elevenlabs_timeout_error():
    """Verify network timeout raises VoiceTimeoutError."""
    tts = ElevenLabsTTSProvider(api_key="el-test-key")

    with patch("urllib.request.urlopen", side_effect=socket.timeout("Socket timeout")):
        with pytest.raises(VoiceTimeoutError, match="timed out"):
            asyncio.run(tts.synthesize("Hello"))


def test_system_tts_provider():
    """Verify SystemTTSProvider generates audio bytes and chunks cleanly."""
    tts = SystemTTSProvider()
    assert tts.name == "system"
    assert tts.is_configured is True

    chunk = asyncio.run(tts.synthesize("Local speech synthesis"))
    assert len(chunk.data) > 0
    assert chunk.is_final is True

    # Stream chunks
    async def _collect():
        collected = []
        async for c in tts.synthesize_stream("Streaming local speech"):
            collected.append(c)
        return collected

    chunks = asyncio.run(_collect())
    assert len(chunks) >= 1
