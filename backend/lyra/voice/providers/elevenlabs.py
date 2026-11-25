"""ElevenLabs Text-to-Speech provider adapter for LYRA."""

import asyncio
import json
import socket
from typing import AsyncIterable
import urllib.error
import urllib.request

from lyra.config.settings import load_settings
from lyra.core.exceptions import (
    VoiceAuthenticationError,
    VoiceExecutionError,
    VoiceInterruptedError,
    VoiceNotConfiguredError,
    VoiceRateLimitError,
    VoiceTimeoutError,
)
from lyra.observability.logging import get_logger
from lyra.voice.base import TextToSpeechProvider
from lyra.voice.models import AudioChunk, CancellationToken

ELEVENLABS_BASE_URL = "https://api.elevenlabs.io/v1/text-to-speech"
DEFAULT_ELEVENLABS_VOICE = "21m00Tcm4TlvDq8ikWAM"  # Rachel voice
CHUNK_SIZE = 4096


class ElevenLabsTTSProvider(TextToSpeechProvider):
    """ElevenLabs Cloud TTS adapter (supports free tier)."""

    def __init__(
        self,
        api_key: str | None = None,
        default_voice_id: str | None = None,
        timeout_seconds: float | None = None,
        voice_id: str | None = None,
    ) -> None:
        settings = load_settings()
        self._api_key = api_key if api_key is not None else settings.elevenlabs_api_key
        resolved_voice_id = (
            default_voice_id
            if default_voice_id is not None
            else voice_id
            if voice_id is not None
            else settings.elevenlabs_voice_id
        ) or DEFAULT_ELEVENLABS_VOICE
        self._default_voice_id = resolved_voice_id
        self._timeout = (
            timeout_seconds if timeout_seconds is not None else settings.voice_timeout_seconds
        )
        self._logger = get_logger("voice.elevenlabs")

    @property
    def name(self) -> str:
        return "elevenlabs"

    @property
    def is_configured(self) -> bool:
        return bool(self._api_key and self._api_key.strip())

    def _build_request(self, text: str, voice_id: str, stream: bool = False) -> urllib.request.Request:
        """Create urllib Request for ElevenLabs endpoint."""
        url = f"{ELEVENLABS_BASE_URL}/{voice_id}"
        if stream:
            url += "/stream"

        payload = {
            "text": text,
            "model_id": "eleven_monolingual_v1",
            "voice_settings": {
                "stability": 0.5,
                "similarity_boost": 0.75,
            },
        }
        data = json.dumps(payload).encode("utf-8")
        headers = {
            "xi-api-key": self._api_key or "",
            "Content-Type": "application/json",
            "Accept": "audio/mpeg",
            "User-Agent": "LYRA-Personal-AI-OS/1.0",
        }
        return urllib.request.Request(url, data=data, headers=headers, method="POST")

    def _handle_http_error(self, err: urllib.error.HTTPError) -> None:
        """Translate urllib HTTP errors into LYRA voice exceptions."""
        body = err.read().decode("utf-8", errors="replace")
        if err.code in (401, 403):
            raise VoiceAuthenticationError(
                f"ElevenLabs authentication failed (HTTP {err.code}): {body}"
            ) from err
        if err.code == 429:
            raise VoiceRateLimitError(
                f"ElevenLabs rate limit exceeded (HTTP 429): {body}"
            ) from err
        raise VoiceExecutionError(
            f"ElevenLabs synthesis failed with HTTP {err.code}: {body}"
        ) from err

    async def synthesize(
        self,
        text: str,
        voice: str | None = None,
        cancellation_token: CancellationToken | None = None,
    ) -> AudioChunk:
        """Synthesize text into complete audio chunk."""
        if not self.is_configured:
            raise VoiceNotConfiguredError("ElevenLabs is not configured with an API key.")

        if cancellation_token and cancellation_token.is_cancelled:
            raise VoiceInterruptedError("Synthesis cancelled before execution.")

        voice_id = voice or self._default_voice_id
        req = self._build_request(text, voice_id=voice_id, stream=False)

        def _do_request() -> bytes:
            try:
                with urllib.request.urlopen(req, timeout=self._timeout) as resp:
                    return resp.read()
            except urllib.error.HTTPError as http_err:
                self._handle_http_error(http_err)
                return b""
            except (urllib.error.URLError, socket.timeout, TimeoutError) as net_err:
                raise VoiceTimeoutError(f"ElevenLabs request timed out: {net_err}") from net_err

        raw_audio = await asyncio.to_thread(_do_request)

        if cancellation_token and cancellation_token.is_cancelled:
            raise VoiceInterruptedError("Synthesis interrupted after download.")

        return AudioChunk(data=raw_audio, mime_type="audio/mpeg", is_final=True)

    async def synthesize_stream(
        self,
        text: str,
        voice: str | None = None,
        cancellation_token: CancellationToken | None = None,
    ) -> AsyncIterable[AudioChunk]:
        """Stream progressive audio chunks with cancellation and voice interruption checks."""
        if not self.is_configured:
            raise VoiceNotConfiguredError("ElevenLabs is not configured with an API key.")

        voice_id = voice or self._default_voice_id
        req = self._build_request(text, voice_id=voice_id, stream=True)

        queue: asyncio.Queue[bytes | None | Exception] = asyncio.Queue(maxsize=16)

        def _streaming_worker() -> None:
            try:
                with urllib.request.urlopen(req, timeout=self._timeout) as resp:
                    while True:
                        if cancellation_token and cancellation_token.is_cancelled:
                            queue.put_nowait(VoiceInterruptedError("Streaming interrupted."))
                            break
                        chunk = resp.read(CHUNK_SIZE)
                        if not chunk:
                            queue.put_nowait(None)  # EOF
                            break
                        queue.put_nowait(chunk)
            except urllib.error.HTTPError as http_err:
                try:
                    self._handle_http_error(http_err)
                except Exception as exc:  # pylint: disable=broad-except
                    queue.put_nowait(exc)
            except (urllib.error.URLError, socket.timeout, TimeoutError) as net_err:
                queue.put_nowait(VoiceTimeoutError(f"ElevenLabs streaming timed out: {net_err}"))
            except Exception as exc:  # pylint: disable=broad-except
                queue.put_nowait(VoiceExecutionError(f"Streaming failure: {exc}"))

        # Launch worker in thread
        worker_task = asyncio.create_task(asyncio.to_thread(_streaming_worker))

        try:
            while True:
                item = await queue.get()
                if item is None:
                    break
                if isinstance(item, Exception):
                    raise item

                if cancellation_token:
                    cancellation_token.check_cancelled()

                yield AudioChunk(data=item, mime_type="audio/mpeg", is_final=False)

            yield AudioChunk(data=b"", mime_type="audio/mpeg", is_final=True)
        finally:
            if cancellation_token and cancellation_token.is_cancelled:
                worker_task.cancel()
