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
from lyra.voice.audio_events import detect_coughs
from lyra.voice.models import CancellationToken
from lyra.voice.providers.system import SystemTTSProvider
from lyra.voice.voices import female_voices, installed_voices, is_female_voice, prepare_speech_text

from app.core.errors import APIError

logger = get_logger("api.voice")

MAX_TTS_CHARS = 2000
DUPLICATE_WINDOW_SECONDS = 20.0
COUGH_COOLDOWN_SECONDS = 600.0  # ask about a cough at most once per 10 minutes per conversation
COUGH_ONLY_REPLIES = (
    "Excuse me, Boss. I noticed you might have coughed. Are you feeling okay?",
    "Boss, are you feeling alright? It sounded like you coughed. Let me know if I can help with anything.",
)


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
            tts_provider = SystemTTSProvider(
                voice_name=tts_provider.voice_name, output_format="wav", rate=tts_provider.rate
            )
        self.tts = tts_provider
        self._recent_audio: dict[str, float] = {}
        self.audio_event_detection = True
        self.cough_detection = True
        self._last_cough_prompt: dict[str, float] = {}
        self._cough_reply_index = 0

    @property
    def tts_ready(self) -> bool:
        # macOS `say` is the system voice; without it (e.g. on a Linux server) only cloud TTS can speak.
        if isinstance(self.tts, SystemTTSProvider):
            return shutil.which("say") is not None
        return bool(getattr(self.tts, "is_configured", False))

    # Preferences ----------------------------------------------------------------
    @property
    def voice_name(self) -> str | None:
        name = getattr(self.tts, "voice_name", None)
        return None if name in (None, "default") else name

    @property
    def speech_rate(self) -> int | None:
        return getattr(self.tts, "rate", None)

    def set_voice(self, name: str | None) -> None:
        if not name:
            return
        if not isinstance(self.tts, SystemTTSProvider):
            raise APIError("VOICE_NOT_SUPPORTED", "Voice selection applies to the system (macOS) voice provider.", 422)
        if name not in {v["name"] for v in installed_voices()}:
            raise APIError("VALIDATION_ERROR", f"Voice '{name}' is not installed on this computer.", 422)
        self.tts.voice_name = name

    def set_rate(self, rate: int | None) -> None:
        if isinstance(self.tts, SystemTTSProvider) and rate:
            self.tts.rate = max(120, min(260, int(rate)))

    # Audio events -----------------------------------------------------------------
    def analyze_audio(self, data: bytes, session_id: str | None) -> list[dict[str, Any]]:
        """Detect non-speech events worth reacting to (respecting settings and cooldown)."""
        if not (self.audio_event_detection and self.cough_detection):
            return []
        try:
            events = [e.to_dict() for e in detect_coughs(data)]
        except Exception as err:  # never let detection break a voice turn
            logger.debug("Audio event detection failed: %s", err)
            return []
        if not events:
            return []
        key = session_id or "_"
        now = time.monotonic()
        if now - self._last_cough_prompt.get(key, -1e9) < COUGH_COOLDOWN_SECONDS:
            return []  # already asked recently; don't keep interrupting
        self._last_cough_prompt[key] = now
        return events

    def cough_only_reply(self) -> str:
        reply = COUGH_ONLY_REPLIES[self._cough_reply_index % len(COUGH_ONLY_REPLIES)]
        self._cough_reply_index += 1
        return reply

    # Status -------------------------------------------------------------------
    def status(self) -> dict[str, Any]:
        return {
            "stt_provider": getattr(self.stt, "name", "unknown"),
            "stt_ready": bool(getattr(self.stt, "is_configured", False)),
            "tts_provider": getattr(self.tts, "name", "unknown"),
            "tts_ready": self.tts_ready,
            "voice": self.voice_name,
            "speech_rate": self.speech_rate,
            "audio_event_detection": self.audio_event_detection,
            "cough_detection": self.cough_detection,
            "accepted_input_formats": ["audio/wav (16-bit PCM)", "audio/aiff", "audio/flac"],
            "system_say_available": shutil.which("say") is not None,
        }

    def list_system_voices(self) -> list[dict[str, Any]]:
        """Installed voices, natural female English voices first (LYRA's voice is female)."""
        ranked = female_voices()
        rank = {v["name"]: i for i, v in enumerate(ranked)}
        voices = [
            {**v, "female": is_female_voice(v["name"]), "recommended": rank.get(v["name"]) == 0}
            for v in installed_voices()
        ]
        return sorted(voices, key=lambda v: (not v["female"], rank.get(v["name"], 999), v["name"]))

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
        clean = prepare_speech_text(text or "")
        if not clean:
            raise APIError("VALIDATION_ERROR", "Text to speak cannot be empty.", 422)
        clean = clean[:MAX_TTS_CHARS]
        if not self.tts_ready:
            raise APIError("VOICE_NOT_CONFIGURED",
                           "Speech synthesis isn't available on this server (set ELEVENLABS_API_KEY and TTS_PROVIDER=elevenlabs).",
                           503)
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
