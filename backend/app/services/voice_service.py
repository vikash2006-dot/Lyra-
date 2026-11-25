"""Voice for the web interface, built on LYRA's existing STT/TTS providers.

Flow: browser microphone -> WAV upload -> STT (FreeSTTProvider / configured) ->
LYRA turn (planner, tools, AI) -> TTS (macOS ``say`` as WAV / ElevenLabs MP3) ->
text + audio back to the browser for playback.
"""

from __future__ import annotations

import asyncio
import base64
import hashlib
import shutil
import subprocess
import time
from typing import Any

from lyra.config.settings import Settings
from lyra.core.exceptions import VoiceError
from lyra.observability.logging import get_logger, sanitize_text
from lyra.voice.models import CancellationToken
from lyra.voice.providers.system import SystemTTSProvider

from app.core.errors import APIError

logger = get_logger("api.voice")

MAX_TTS_CHARS = 2000
DUPLICATE_WINDOW_SECONDS = 20.0


def detect_audio_format(data: bytes) -> str | None:
    """Formats SpeechRecognition's AudioFile can decode without ffmpeg."""
    if len(data) >= 12 and data[:4] == b"RIFF" and data[8:12] == b"WAVE":
        return "wav"
    if len(data) >= 12 and data[:4] == b"FORM" and data[8:12] in (b"AIFF", b"AIFC"):
        return "aiff"
    if data[:4] == b"fLaC":
        return "flac"
    return None


class VoiceService:
    def __init__(self, settings: Settings, stt_provider: Any, tts_provider: Any) -> None:
        self.settings = settings
        self.stt = stt_provider
        # Browsers cannot play AIFF; ask macOS `say` for 16-bit PCM WAV instead.
        if isinstance(tts_provider, SystemTTSProvider):
            tts_provider = SystemTTSProvider(voice_name=tts_provider.voice_name, output_format="wav")
        self.tts = tts_provider
        self._recent_audio: dict[str, float] = {}

    # Status -------------------------------------------------------------------
    def status(self) -> dict[str, Any]:
        return {
            "stt_provider": getattr(self.stt, "name", "unknown"),
            "stt_ready": bool(getattr(self.stt, "is_configured", False)),
            "tts_provider": getattr(self.tts, "name", "unknown"),
            "tts_ready": bool(getattr(self.tts, "is_configured", False)),
            "accepted_input_formats": ["audio/wav (16-bit PCM)", "audio/aiff", "audio/flac"],
            "system_say_available": shutil.which("say") is not None,
        }

    def list_system_voices(self) -> list[dict[str, str]]:
        say = shutil.which("say")
        if not say:
            return []
        try:
            out = subprocess.run([say, "-v", "?"], capture_output=True, text=True, timeout=5).stdout
        except (OSError, subprocess.SubprocessError):
            return []
        voices = []
        for line in out.splitlines():
            head, _, sample = line.partition("#")
            bits = head.split()
            if len(bits) >= 2:
                voices.append({"name": " ".join(bits[:-1]), "locale": bits[-1], "sample": sample.strip()})
        return voices

    # Validation ---------------------------------------------------------------
    def validate_audio(self, data: bytes, max_bytes: int) -> str:
        if not data:
            raise APIError("EMPTY_AUDIO", "No audio was received.", 422)
        if len(data) > max_bytes:
            raise APIError("PAYLOAD_TOO_LARGE", "Audio clip is too large.", 413)
        fmt = detect_audio_format(data)
        if fmt is None:
            raise APIError(
                "UNSUPPORTED_AUDIO",
                "Unsupported audio format. Send 16-bit PCM WAV (the LYRA web app does this automatically).",
                415,
            )
        return fmt

    def check_duplicate(self, data: bytes) -> None:
        """Reject the exact same clip re-sent within a short window (double submits)."""
        now = time.monotonic()
        self._recent_audio = {h: t for h, t in self._recent_audio.items() if now - t < DUPLICATE_WINDOW_SECONDS}
        digest = hashlib.sha256(data).hexdigest()
        if digest in self._recent_audio:
            raise APIError("DUPLICATE_AUDIO", "This audio clip was already processed.", 409)
        self._recent_audio[digest] = now

    # Operations ---------------------------------------------------------------
    async def transcribe(self, data: bytes, max_bytes: int) -> dict[str, Any]:
        fmt = self.validate_audio(data, max_bytes)
        if not getattr(self.stt, "is_configured", False):
            raise APIError("VOICE_NOT_CONFIGURED", "Speech recognition is not configured.", 503)
        try:
            result = await asyncio.wait_for(
                self.stt.transcribe(data, mime_type=f"audio/{fmt}"),
                timeout=max(self.settings.voice_timeout_seconds, 10.0) + 15.0,
            )
        except asyncio.TimeoutError as err:
            raise APIError("VOICE_TIMEOUT", "Speech recognition timed out.", 504) from err
        except VoiceError as err:
            logger.warning("STT failed: %s", sanitize_text(str(err)))
            raise APIError("TRANSCRIPTION_FAILED", "Speech recognition failed. Please try again.", 502) from err
        return {
            "text": (result.text or "").strip(),
            "confidence": result.confidence,
            "language": result.language,
        }

    async def speak(self, text: str, voice: str | None = None,
                    token: CancellationToken | None = None) -> dict[str, Any]:
        clean = (text or "").strip()
        if not clean:
            raise APIError("VALIDATION_ERROR", "Text to speak cannot be empty.", 422)
        clean = clean[:MAX_TTS_CHARS]
        if not getattr(self.tts, "is_configured", False):
            raise APIError("VOICE_NOT_CONFIGURED", "Speech synthesis is not configured.", 503)
        try:
            chunk = await self.tts.synthesize(clean, voice=voice, cancellation_token=token)
        except VoiceError as err:
            logger.warning("TTS failed: %s", sanitize_text(str(err)))
            raise APIError("SYNTHESIS_FAILED", "Speech synthesis failed.", 502) from err
        return {
            "mime_type": chunk.mime_type,
            "audio_base64": base64.b64encode(chunk.data).decode("ascii"),
            "bytes": len(chunk.data),
            "provider": getattr(self.tts, "name", "unknown"),
        }
