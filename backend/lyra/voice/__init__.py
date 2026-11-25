"""LYRA Voice subsystem."""

from lyra.voice.base import SpeechToTextProvider, TextToSpeechProvider
from lyra.voice.capture import MicrophoneCapture
from lyra.voice.conversation import VoiceConversationManager
from lyra.voice.models import AudioChunk, CancellationToken, TranscriptionResult
from lyra.voice.pipeline import VoicePipeline
from lyra.voice.player import AudioPlayer
from lyra.voice.providers.elevenlabs import ElevenLabsTTSProvider
from lyra.voice.providers.free_stt import FreeSTTProvider
from lyra.voice.providers.mock import MockSTTProvider, MockTTSProvider
from lyra.voice.providers.system import SystemTTSProvider

__all__ = [
    "SpeechToTextProvider",
    "TextToSpeechProvider",
    "MicrophoneCapture",
    "AudioPlayer",
    "VoiceConversationManager",
    "FreeSTTProvider",
    "AudioChunk",
    "TranscriptionResult",
    "CancellationToken",
    "VoicePipeline",
    "ElevenLabsTTSProvider",
    "SystemTTSProvider",
    "MockSTTProvider",
    "MockTTSProvider",
]
