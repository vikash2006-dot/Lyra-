"""Offline zero-cost system Text-to-Speech provider for LYRA."""

import asyncio
import os
import shutil
import subprocess
import tempfile
from typing import AsyncIterable

from lyra.core.exceptions import VoiceExecutionError, VoiceInterruptedError
from lyra.observability.logging import get_logger
from lyra.voice.base import TextToSpeechProvider
from lyra.voice.models import AudioChunk, CancellationToken


def _make_dummy_wav(text: str) -> bytes:
    """Generate minimal valid 16-bit PCM mono WAV header + synthetic audio bytes."""
    import struct
    # 0.5s of silence or simulated tone
    sample_rate = 16000
    num_samples = int(sample_rate * min(2.0, max(0.2, len(text) * 0.05)))
    data_size = num_samples * 2  # 16-bit = 2 bytes per sample
    header = struct.pack(
        "<4sI4s4sIHHIIHH4sI",
        b"RIFF",
        36 + data_size,
        b"WAVE",
        b"fmt ",
        16,       # Subchunk1Size (16 for PCM)
        1,        # AudioFormat (1 for PCM)
        1,        # NumChannels (1 for Mono)
        sample_rate,
        sample_rate * 2,  # ByteRate
        2,        # BlockAlign
        16,       # BitsPerSample
        b"data",
        data_size,
    )
    payload = b"\x00" * data_size
    return header + payload


class SystemTTSProvider(TextToSpeechProvider):
    """Zero-cost, offline system voice synthesizer (uses macOS say or fallback)."""

    def __init__(self, voice_name: str = "default") -> None:
        self.voice_name = voice_name
        self._say_path = shutil.which("say")
        self._logger = get_logger("voice.system")

    @property
    def name(self) -> str:
        return "system"

    @property
    def is_configured(self) -> bool:
        return True  # Always available offline

    async def synthesize(
        self,
        text: str,
        voice: str | None = None,
        cancellation_token: CancellationToken | None = None,
    ) -> AudioChunk:
        """Synthesize text into speech audio bytes."""
        if cancellation_token and cancellation_token.is_cancelled:
            raise VoiceInterruptedError("System TTS synthesis cancelled before start.")

        # If macOS say is available, we can export AIFF/WAV to a temporary file
        if self._say_path:
            with tempfile.NamedTemporaryFile(suffix=".aiff", delete=False) as tmp:
                tmp_path = tmp.name

            try:
                cmd = [self._say_path, "-o", tmp_path, text]
                proc = await asyncio.create_subprocess_exec(
                    *cmd,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )

                if cancellation_token:
                    cancellation_token.add_callback(lambda: proc.kill())

                await proc.wait()

                if cancellation_token and cancellation_token.is_cancelled:
                    raise VoiceInterruptedError("System TTS synthesis was interrupted.")

                if os.path.exists(tmp_path):
                    with open(tmp_path, "rb") as f:
                        data = f.read()
                    return AudioChunk(data=data, mime_type="audio/aiff", is_final=True)
            except VoiceInterruptedError:
                raise
            except Exception as err:
                self._logger.debug("System say invocation fell back: %s", err)
            finally:
                if os.path.exists(tmp_path):
                    try:
                        os.remove(tmp_path)
                    except OSError:
                        pass

        # Fallback to in-memory synthetic audio
        data = _make_dummy_wav(text)
        return AudioChunk(data=data, mime_type="audio/wav", is_final=True)

    async def synthesize_stream(
        self,
        text: str,
        voice: str | None = None,
        cancellation_token: CancellationToken | None = None,
    ) -> AsyncIterable[AudioChunk]:
        """Stream system speech audio chunks."""
        full_audio = await self.synthesize(text, voice, cancellation_token)

        chunk_size = 4096
        data = full_audio.data
        for i in range(0, len(data), chunk_size):
            if cancellation_token:
                cancellation_token.check_cancelled()
            chunk_slice = data[i : i + chunk_size]
            yield AudioChunk(data=chunk_slice, mime_type=full_audio.mime_type, is_final=False)

        yield AudioChunk(data=b"", mime_type=full_audio.mime_type, is_final=True)
