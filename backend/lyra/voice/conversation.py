"""Interactive continuous voice conversation manager for LYRA."""

import asyncio
import re
import sys
from typing import Callable

from lyra.companion.orchestrator import CompanionOrchestrator
from lyra.companion.session import Session
from lyra.config.settings import Settings
from lyra.core.exceptions import (
    EmptyAudioError,
    MicrophoneUnavailableError,
    SilenceTimeoutError,
    VoiceExecutionError,
    VoiceInterruptedError,
)
from lyra.models.stream import StreamError, TextDelta
from lyra.observability.logging import get_logger
from lyra.voice.base import SpeechToTextProvider, TextToSpeechProvider
from lyra.voice.capture import MicrophoneCapture
from lyra.voice.models import CancellationToken
from lyra.voice.player import AudioPlayer
from lyra.voice.voices import prepare_speech_text

logger = get_logger("voice.conversation")

# Split only on real sentence endings (not ":" or line breaks) so speech isn't fragmented.
_SENTENCE_SPLIT_REGEX = re.compile(r"((?<=[.?!])\s+)")
_FIRST_CHUNK_MIN = 20     # speak the first sentence quickly
_LATER_CHUNK_MIN = 160    # then merge sentences into fuller chunks for continuous delivery
_EXIT_PHRASES = frozenset({"exit", "quit", "goodbye", "bye", "stop", "exit voice", "quit voice"})


class VoiceConversationManager:
    """Manages the continuous voice-first interactive loop:

    🎤 Listening -> 🧠 Thinking -> 🔊 Speaking -> 🎤 Listening...
    """

    def __init__(
        self,
        orchestrator: CompanionOrchestrator,
        session: Session,
        capture: MicrophoneCapture,
        stt_provider: SpeechToTextProvider,
        tts_provider: TextToSpeechProvider,
        player: AudioPlayer,
        settings: Settings,
        status_callback: Callable[[str], None] | None = None,
    ) -> None:
        self.orchestrator = orchestrator
        self.session = session
        self.capture = capture
        self.stt_provider = stt_provider
        self.tts_provider = tts_provider
        self.player = player
        self.settings = settings
        self._status_callback = status_callback
        self._cancellation_token = CancellationToken()

    def set_status(self, status: str) -> None:
        """Report current status to the user interface."""
        if self._status_callback:
            self._status_callback(status)
        else:
            sys.stdout.write(f"\r{status}\033[K\n")
            sys.stdout.flush()

    async def _speak_sentence(self, sentence: str, token: CancellationToken) -> None:
        """Speak a single sentence through the configured TTS provider and speaker player."""
        clean = prepare_speech_text(sentence)
        if not clean:
            return

        if token.is_cancelled:
            return

        logger.debug("Speaking sentence: %s", clean[:40])
        try:
            if self.tts_provider.name == "system":
                voice = getattr(self.tts_provider, "voice_name", None)
                await self.player.speak_text_system(
                    clean,
                    voice=None if voice in (None, "default") else voice,
                    cancellation_token=token,
                    rate=getattr(self.tts_provider, "rate", None),
                )
            else:
                chunk = await self.tts_provider.synthesize(clean, cancellation_token=token)
                await self.player.play_chunk(chunk, cancellation_token=token)
        except VoiceInterruptedError:
            logger.info("Speech playback was interrupted by user.")
        except Exception as err:
            logger.warning("Failed to speak sentence '%s': %s", clean[:30], err)

    async def process_one_turn(self) -> bool:
        """Execute one complete voice turn:

        Microphone -> STT -> Gemini -> Streaming Sentence TTS -> Speaker

        Returns:
            False if session should terminate (exit phrase detected), True to continue.
        """
        self._cancellation_token = CancellationToken()

        # 1. Listening State
        self.set_status("🎤 Listening...")
        try:
            audio_bytes = await self.capture.capture_turn(
                timeout=self.settings.voice_input_timeout_seconds
            )
        except SilenceTimeoutError:
            logger.debug("Silence timeout; listening again...")
            return True
        except EmptyAudioError:
            logger.debug("Empty audio captured; listening again...")
            return True
        except MicrophoneUnavailableError as mic_err:
            sys.stderr.write(f"\n[Microphone Error]: {mic_err}\n")
            sys.stderr.write("Please verify microphone permissions in macOS System Settings -> Privacy & Security -> Microphone.\n")
            return False

        # 2. Thinking State (STT + LLM Synthesis)
        self.set_status("🧠 Thinking...")
        try:
            transcription = await self.stt_provider.transcribe(audio_bytes)
            user_text = transcription.text.strip()
        except Exception as stt_err:
            logger.warning("STT transcription error: %s", stt_err)
            self.set_status("⚠️ Could not recognize speech. Please try again.")
            await asyncio.sleep(1.0)
            return True

        if not user_text:
            logger.debug("Unintelligible speech received.")
            return True

        # Print user message to console
        sys.stdout.write(f"\nYou: {user_text}\n")
        sys.stdout.flush()

        # Check for exit commands
        normalized = user_text.lower().rstrip(".?! ")
        if normalized in _EXIT_PHRASES:
            self.set_status("🔊 Speaking...")
            sys.stdout.write("LYRA: See you soon, Boss. Take care!\n\n")
            sys.stdout.flush()
            await self._speak_sentence("See you soon, Boss. Take care!", self._cancellation_token)
            return False

        # 3. Speaking State (Streaming response from Gemini with sentence buffering)
        self.set_status("🔊 Speaking...")
        sys.stdout.write("LYRA: ")
        sys.stdout.flush()

        sentence_buffer = ""
        accumulated_response: list[str] = []
        speech_queue: asyncio.Queue[str | None] = asyncio.Queue()
        spoken_chunks = 0

        async def speaker() -> None:
            # Speaks queued chunks back-to-back while the reply keeps streaming in.
            while True:
                chunk = await speech_queue.get()
                if chunk is None or self._cancellation_token.is_cancelled:
                    return
                await self._speak_sentence(chunk, self._cancellation_token)

        speaker_task = asyncio.create_task(speaker())

        def flush_ready(final: bool = False) -> None:
            nonlocal sentence_buffer, spoken_chunks
            parts = _SENTENCE_SPLIT_REGEX.split(sentence_buffer)
            complete = "".join(parts[:-1]).strip()  # everything up to the last sentence ending
            pending = parts[-1] if parts else ""
            threshold = _FIRST_CHUNK_MIN if spoken_chunks == 0 else _LATER_CHUNK_MIN
            if final:
                text = sentence_buffer.strip()
                if text:
                    speech_queue.put_nowait(text)
                sentence_buffer = ""
            elif complete and len(complete) >= threshold:
                speech_queue.put_nowait(complete)
                spoken_chunks += 1
                sentence_buffer = pending

        try:
            async for event in self.orchestrator.stream_turn(self.session, user_text):
                if isinstance(event, TextDelta):
                    delta = event.delta
                    sys.stdout.write(delta)
                    sys.stdout.flush()
                    accumulated_response.append(delta)
                    sentence_buffer += delta
                    flush_ready()

                elif isinstance(event, StreamError):
                    sys.stdout.write(f"\n[Error: {event.error_message}]\n")
                    sys.stdout.flush()
                    if not accumulated_response and event.error_message:
                        sentence_buffer = event.error_message
                    break

            # Speak any trailing text left in the buffer, then wait for speech to finish.
            if not self._cancellation_token.is_cancelled:
                flush_ready(final=True)
            speech_queue.put_nowait(None)
            await speaker_task

            sys.stdout.write("\n\n")
            sys.stdout.flush()
        except Exception as err:
            speaker_task.cancel()
            logger.error("Error during conversation turn: %s", err)
            sys.stdout.write(f"\n[Conversation error: {err}]\n\n")
            sys.stdout.flush()

        return True

    async def run(self) -> None:
        """Run continuous voice conversation loop until exit is requested."""
        sys.stdout.write("\n==================================================\n")
        sys.stdout.write("LYRA Voice Mode\n")
        sys.stdout.write(f"STT: {self.stt_provider.name} | TTS: {self.tts_provider.name}\n")
        sys.stdout.write("Say 'exit' or 'quit', or press Ctrl+C to return to terminal.\n")
        sys.stdout.write("==================================================\n\n")
        sys.stdout.flush()

        while True:
            try:
                should_continue = await self.process_one_turn()
                if not should_continue:
                    break
            except (KeyboardInterrupt, asyncio.CancelledError):
                sys.stdout.write("\n\n[Voice mode interrupted. Goodbye!]\n")
                sys.stdout.flush()
                break
            except Exception as loop_err:
                logger.error("Unexpected error in voice loop: %s", loop_err)
                sys.stdout.write(f"\n[Voice error: {loop_err}]\n")
                sys.stdout.flush()
                await asyncio.sleep(1.0)
