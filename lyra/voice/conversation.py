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

logger = get_logger("voice.conversation")

_SENTENCE_SPLIT_REGEX = re.compile(r"([.?!:\n]+(?:\s+|$))")
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
        clean = sentence.strip()
        if not clean:
            return

        if token.is_cancelled:
            return

        logger.debug("Speaking sentence: %s", clean[:40])
        try:
            if self.tts_provider.name == "system":
                await self.player.speak_text_system(clean, cancellation_token=token)
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
            sys.stdout.write("LYRA: Goodbye!\n\n")
            sys.stdout.flush()
            await self._speak_sentence("Goodbye!", self._cancellation_token)
            return False

        # 3. Speaking State (Streaming response from Gemini with sentence buffering)
        self.set_status("🔊 Speaking...")
        sys.stdout.write("LYRA: ")
        sys.stdout.flush()

        sentence_buffer = ""
        accumulated_response = []

        try:
            async for event in self.orchestrator.stream_turn(self.session, user_text):
                if isinstance(event, TextDelta):
                    delta = event.delta
                    sys.stdout.write(delta)
                    sys.stdout.flush()
                    accumulated_response.append(delta)
                    sentence_buffer += delta

                    # Check for sentence boundaries to speak in chunks
                    parts = _SENTENCE_SPLIT_REGEX.split(sentence_buffer)
                    if len(parts) > 2:
                        # We have at least one complete sentence!
                        # parts[0] is the sentence text, parts[1] is the delimiter
                        complete_sentence = parts[0] + parts[1]
                        sentence_buffer = "".join(parts[2:])
                        await self._speak_sentence(complete_sentence, self._cancellation_token)

                elif isinstance(event, StreamError):
                    sys.stdout.write(f"\n[Error: {event.error_message}]\n")
                    sys.stdout.flush()
                    if not accumulated_response and event.error_message:
                        await self._speak_sentence(event.error_message, self._cancellation_token)
                    break

            # Speak any trailing text left in sentence buffer
            if sentence_buffer.strip() and not self._cancellation_token.is_cancelled:
                await self._speak_sentence(sentence_buffer, self._cancellation_token)

            sys.stdout.write("\n\n")
            sys.stdout.flush()
        except Exception as err:
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
