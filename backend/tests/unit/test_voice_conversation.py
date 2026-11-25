"""Unit tests for VoiceConversationManager."""

import asyncio
from unittest.mock import AsyncMock, MagicMock
import pytest

from lyra.config.settings import Settings
from lyra.core.exceptions import SilenceTimeoutError
from lyra.models.stream import TextDelta
from lyra.voice.conversation import VoiceConversationManager
from lyra.voice.models import TranscriptionResult


class AsyncStreamIterator:
    """Helper to mock an asynchronous stream of response events."""

    def __init__(self, deltas: list[str]) -> None:
        self.deltas = deltas
        self.idx = 0

    def __aiter__(self):
        return self

    async def __anext__(self):
        if self.idx < len(self.deltas):
            delta = self.deltas[self.idx]
            self.idx += 1
            return TextDelta(delta=delta)
        raise StopAsyncIteration


def test_voice_conversation_manager_turn_and_exit(capsys: pytest.CaptureFixture[str]) -> None:
    """Verify voice conversation loop handles user speech, streams response, speaks sentences, and exits cleanly."""
    async def _run():
        settings = Settings(voice_input_timeout_seconds=5.0)

        mock_orchestrator = MagicMock()
        mock_session = MagicMock()

        dummy_wav = b"RIFF" + b"\x00" * 40
        mock_capture = MagicMock()
        mock_capture.capture_turn = AsyncMock(side_effect=[dummy_wav, dummy_wav])

        mock_stt = MagicMock()
        mock_stt.name = "free_stt"
        mock_stt.transcribe = AsyncMock(side_effect=[
            TranscriptionResult(text="Hello Lyra", confidence=0.95),
            TranscriptionResult(text="exit", confidence=0.95),
        ])

        mock_tts = MagicMock()
        mock_tts.name = "system"

        mock_player = MagicMock()
        mock_player.speak_text_system = AsyncMock()

        deltas = ["Hello! ", "I am Lyra, ", "your personal AI operating system. ", "How can I help you today?"]
        mock_orchestrator.stream_turn.return_value = AsyncStreamIterator(deltas)

        statuses: list[str] = []
        manager = VoiceConversationManager(
            orchestrator=mock_orchestrator,
            session=mock_session,
            capture=mock_capture,
            stt_provider=mock_stt,
            tts_provider=mock_tts,
            player=mock_player,
            settings=settings,
            status_callback=lambda s: statuses.append(s),
        )

        await manager.run()

        assert "🎤 Listening..." in statuses
        assert "🧠 Thinking..." in statuses
        assert "🔊 Speaking..." in statuses
        assert mock_player.speak_text_system.called

    asyncio.run(_run())

    captured = capsys.readouterr()
    assert "You: Hello Lyra" in captured.out
    assert "LYRA: Hello! I am Lyra, your personal AI operating system. How can I help you today?" in captured.out
    assert "Goodbye!" in captured.out


def test_voice_conversation_silence_timeout_continues() -> None:
    """Verify that SilenceTimeoutError does not break the loop and continues listening."""
    async def _run():
        settings = Settings(voice_input_timeout_seconds=5.0)
        mock_orchestrator = MagicMock()
        mock_session = MagicMock()

        dummy_wav = b"RIFF" + b"\x00" * 40
        mock_capture = MagicMock()
        mock_capture.capture_turn = AsyncMock(side_effect=[
            SilenceTimeoutError("No speech"),
            dummy_wav,
        ])

        mock_stt = MagicMock()
        mock_stt.name = "free_stt"
        mock_stt.transcribe = AsyncMock(return_value=TranscriptionResult(text="quit", confidence=0.9))

        mock_tts = MagicMock()
        mock_tts.name = "system"
        mock_player = MagicMock()
        mock_player.speak_text_system = AsyncMock()

        manager = VoiceConversationManager(
            orchestrator=mock_orchestrator,
            session=mock_session,
            capture=mock_capture,
            stt_provider=mock_stt,
            tts_provider=mock_tts,
            player=mock_player,
            settings=settings,
        )

        await manager.run()
        assert mock_capture.capture_turn.call_count == 2

    asyncio.run(_run())
