"""Audio speaker playback implementation for LYRA voice interaction."""

import asyncio
import os
import shutil
import subprocess
import tempfile
from typing import Sequence

from lyra.core.exceptions import VoiceExecutionError, VoiceInterruptedError
from lyra.observability.logging import get_logger
from lyra.voice.models import AudioChunk, CancellationToken

logger = get_logger("voice.player")


class AudioPlayer:
    """Plays audio through the host machine speakers with interruption and cancellation support."""

    def __init__(self) -> None:
        self._afplay_path = shutil.which("afplay")  # macOS native audio player
        self._say_path = shutil.which("say")        # macOS native speech synthesizer
        self._aplay_path = shutil.which("aplay")    # Linux ALSA player

    def _determine_suffix(self, mime_type: str) -> str:
        if "wav" in mime_type:
            return ".wav"
        if "aiff" in mime_type:
            return ".aiff"
        if "mpeg" in mime_type or "mp3" in mime_type:
            return ".mp3"
        return ".wav"

    async def speak_text_system(
        self,
        text: str,
        voice: str | None = None,
        cancellation_token: CancellationToken | None = None,
    ) -> None:
        """Speak text directly through the system speech synthesizer (macOS say)."""
        clean_text = text.strip()
        if not clean_text:
            return

        if cancellation_token and cancellation_token.is_cancelled:
            raise VoiceInterruptedError("Speech cancelled before starting.")

        if not self._say_path:
            logger.debug("System 'say' utility not found; skipping direct system speak")
            return

        cmd = [self._say_path]
        if voice:
            cmd.extend(["-v", voice])
        cmd.append(clean_text)

        logger.debug("Running system speak: %s", clean_text[:40])
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )

        if cancellation_token:
            cancellation_token.add_callback(lambda: self._kill_proc(proc))

        try:
            await proc.wait()
        except asyncio.CancelledError:
            self._kill_proc(proc)
            raise VoiceInterruptedError("Speech playback was cancelled.")

        if cancellation_token and cancellation_token.is_cancelled:
            raise VoiceInterruptedError("Speech playback was interrupted.")

    async def play_chunk(
        self,
        chunk: AudioChunk,
        cancellation_token: CancellationToken | None = None,
    ) -> None:
        """Play binary audio chunk through speakers via native media player."""
        if not chunk.data:
            return

        if cancellation_token and cancellation_token.is_cancelled:
            raise VoiceInterruptedError("Audio playback cancelled before starting.")

        player_bin = self._afplay_path or self._aplay_path
        if not player_bin:
            logger.debug("No native audio player found on system (afplay/aplay).")
            return

        suffix = self._determine_suffix(chunk.mime_type)
        with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp_file:
            tmp_path = tmp_file.name
            tmp_file.write(chunk.data)

        try:
            cmd = [player_bin, tmp_path]
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )

            if cancellation_token:
                cancellation_token.add_callback(lambda: self._kill_proc(proc))

            try:
                await proc.wait()
            except asyncio.CancelledError:
                self._kill_proc(proc)
                raise VoiceInterruptedError("Audio playback was cancelled.")

            if cancellation_token and cancellation_token.is_cancelled:
                raise VoiceInterruptedError("Audio playback was interrupted.")
        finally:
            if os.path.exists(tmp_path):
                try:
                    os.remove(tmp_path)
                except OSError:
                    pass

    @staticmethod
    def _kill_proc(proc: asyncio.subprocess.Process) -> None:
        try:
            proc.kill()
        except ProcessLookupError:
            pass
        except Exception as err:
            logger.debug("Error terminating audio playback process: %s", err)
