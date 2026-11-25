"""Unit tests for LYRA VoicePipeline."""

import asyncio
import pytest

from lyra.companion.orchestrator import CompanionOrchestrator
from lyra.companion.session import Session
from lyra.core.exceptions import VoiceExecutionError
from lyra.models.messages import AIRequest, AIResponse, Role
from lyra.providers.base import AIProvider
from lyra.routing.router import ModelRouter
from lyra.voice.models import AudioChunk
from lyra.voice.pipeline import VoicePipeline
from lyra.voice.providers.mock import MockSTTProvider, MockTTSProvider


class DummyVoiceAIProvider(AIProvider):
    @property
    def name(self) -> str:
        return "voice-ai"

    @property
    def is_configured(self) -> bool:
        return True

    async def generate(self, request: AIRequest) -> AIResponse:
        user_msg = request.messages[-1].content
        return AIResponse(
            content=f"LYRA heard: {user_msg}",
            model="mock-voice-v1",
            role=Role.ASSISTANT,
        )


def test_voice_pipeline_end_to_end_turn():
    """Verify complete turn: audio in -> STT -> Orchestrator -> TTS stream out."""
    router = ModelRouter(providers=[DummyVoiceAIProvider()])
    orchestrator = CompanionOrchestrator(router=router)
    stt = MockSTTProvider(fixed_text="What is the mission of LYRA?")
    tts = MockTTSProvider(chunk_delay=0.001)

    pipeline = VoicePipeline(orchestrator=orchestrator, stt_provider=stt, tts_provider=tts)
    session = Session()

    async def _run():
        reply_text, stream = await pipeline.process_audio_turn(
            session=session,
            audio_data=b"mock_mic_audio",
        )

        chunks = []
        async for chunk in stream:
            chunks.append(chunk.data)

        return reply_text, chunks

    reply, audio_chunks = asyncio.run(_run())

    assert "LYRA heard: What is the mission of LYRA?" in reply
    assert len(session.messages) == 2
    assert session.messages[0].content == "What is the mission of LYRA?"
    assert session.messages[1].content == reply
    assert len(audio_chunks) == 4  # 3 content chunks + 1 final


def test_voice_pipeline_interruption():
    """Verify calling pipeline.interrupt() halts active speech synthesis stream."""
    router = ModelRouter(providers=[DummyVoiceAIProvider()])
    orchestrator = CompanionOrchestrator(router=router)
    stt = MockSTTProvider(fixed_text="Speak a long sentence")
    tts = MockTTSProvider(chunk_delay=0.05)

    pipeline = VoicePipeline(orchestrator=orchestrator, stt_provider=stt, tts_provider=tts)
    session = Session()

    async def _run():
        reply_text, stream = await pipeline.process_audio_turn(
            session=session,
            audio_data=b"mock_mic_audio",
        )

        chunks = []
        async for chunk in stream:
            chunks.append(chunk.data)
            pipeline.interrupt()  # Interrupt immediately after first chunk

        return reply_text, chunks

    reply, audio_chunks = asyncio.run(_run())
    assert "LYRA heard:" in reply
    # Because interruption occurred, stream stopped early and appended final empty chunk
    assert len(audio_chunks) < 4


def test_voice_pipeline_unconfigured_tts_graceful_degradation():
    """Verify pipeline returns text response even if TTS is unconfigured or absent."""
    router = ModelRouter(providers=[DummyVoiceAIProvider()])
    orchestrator = CompanionOrchestrator(router=router)
    stt = MockSTTProvider(fixed_text="Hello without voice output")

    # tts_provider=None simulates missing voice credentials/provider
    pipeline = VoicePipeline(orchestrator=orchestrator, stt_provider=stt, tts_provider=None)
    session = Session()

    async def _run():
        reply_text, stream = await pipeline.process_audio_turn(
            session=session,
            audio_data=b"audio",
        )
        chunks = [c async for c in stream]
        return reply_text, chunks

    reply, chunks = asyncio.run(_run())
    assert "LYRA heard: Hello without voice output" in reply
    assert len(chunks) == 1
    assert chunks[0].data == b""  # Empty audio stream


def test_voice_pipeline_missing_stt():
    """Verify pipeline raises VoiceExecutionError if STT provider is missing."""
    router = ModelRouter(providers=[DummyVoiceAIProvider()])
    orchestrator = CompanionOrchestrator(router=router)

    pipeline = VoicePipeline(orchestrator=orchestrator, stt_provider=None, tts_provider=None)
    session = Session()

    with pytest.raises(VoiceExecutionError, match="Transcription failed"):
        asyncio.run(pipeline.process_audio_turn(session=session, audio_data=b"audio"))
