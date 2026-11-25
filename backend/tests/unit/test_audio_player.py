"""Unit tests for AudioPlayer."""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch
import pytest

from lyra.core.exceptions import VoiceInterruptedError
from lyra.voice.models import AudioChunk, CancellationToken
from lyra.voice.player import AudioPlayer


def test_audio_player_speak_text_system() -> None:
    """Verify speak_text_system invokes system 'say' process."""
    async def _run():
        player = AudioPlayer()
        player._say_path = "/usr/bin/say"

        mock_proc = AsyncMock()
        mock_proc.wait.return_value = 0

        with patch("asyncio.create_subprocess_exec", return_value=mock_proc) as mock_exec:
            await player.speak_text_system("Hello world", voice="Samantha")

        assert mock_exec.called
        args = mock_exec.call_args[0]
        assert args[0] == "/usr/bin/say"
        assert "-v" in args
        assert "Samantha" in args
        assert "Hello world" in args

    asyncio.run(_run())


def test_audio_player_speak_text_cancelled() -> None:
    """Verify speak_text_system respects already cancelled token."""
    async def _run():
        player = AudioPlayer()
        token = CancellationToken()
        token.cancel()

        with pytest.raises(VoiceInterruptedError):
            await player.speak_text_system("Will not speak", cancellation_token=token)

    asyncio.run(_run())


def test_audio_player_play_chunk_afplay() -> None:
    """Verify play_chunk writes temp file and calls afplay."""
    async def _run():
        player = AudioPlayer()
        player._afplay_path = "/usr/bin/afplay"

        chunk = AudioChunk(data=b"RIFF" + b"\x00" * 40, mime_type="audio/wav")
        mock_proc = AsyncMock()
        mock_proc.wait.return_value = 0

        with patch("asyncio.create_subprocess_exec", return_value=mock_proc) as mock_exec:
            await player.play_chunk(chunk)

        assert mock_exec.called
        args = mock_exec.call_args[0]
        assert args[0] == "/usr/bin/afplay"

    asyncio.run(_run())
