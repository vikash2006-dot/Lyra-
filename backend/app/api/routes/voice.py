"""Voice APIs: speech-to-text, text-to-speech, and full voice commands."""

from __future__ import annotations

from fastapi import APIRouter, File, Form, Request, UploadFile

from app.api.deps import get_services, rate_limit
from app.core.errors import ok
from app.schemas import SpeakRequest

router = APIRouter(tags=["voice"])


async def _read_audio(request: Request, audio: UploadFile) -> bytes:
    services = get_services(request)
    data = await audio.read(services.config.max_audio_bytes + 1)
    services.voice.validate_audio(data, services.config.max_audio_bytes)
    return data


@router.get("/voice/status")
async def voice_status(request: Request) -> dict:
    return ok(get_services(request).voice.status())


@router.get("/voice/voices")
async def list_voices(request: Request) -> dict:
    return ok(get_services(request).voice.list_system_voices())


@router.post("/voice/transcribe")
async def transcribe(request: Request, audio: UploadFile = File(...)) -> dict:
    rate_limit(request, "voice")
    services = get_services(request)
    data = await _read_audio(request, audio)
    return ok(await services.voice.transcribe(data, services.config.max_audio_bytes), "Transcribed")


@router.post("/voice/speak")
async def speak(body: SpeakRequest, request: Request) -> dict:
    rate_limit(request, "voice")
    return ok(await get_services(request).voice.speak(body.text, body.voice), "Synthesized")


@router.post("/voice/command")
async def voice_command(
    request: Request,
    audio: UploadFile = File(...),
    session_id: str | None = Form(None),
    speak: bool = Form(True),
    voice: str | None = Form(None),
) -> dict:
    """Audio in -> transcription -> LYRA turn (tools if needed) -> reply text + speech."""
    rate_limit(request, "voice")
    services = get_services(request)
    data = await _read_audio(request, audio)
    services.voice.check_duplicate(data)
    transcript = await services.voice.transcribe(data, services.config.max_audio_bytes)
    audio_events = services.voice.analyze_audio(data, session_id)
    if not transcript["text"]:
        if audio_events:
            reply = services.voice.cough_only_reply()
            audio_out = await services.voice.speak(reply, voice) if speak else None
            return ok({"transcript": "", "response": reply, "audio": audio_out, "session_id": session_id,
                       "audio_events": audio_events}, "Audio event detected")
        return ok({"transcript": "", "response": None, "audio": None, "session_id": session_id,
                   "audio_events": []}, "No speech detected")
    turn = await services.chat.run_turn(
        transcript["text"], session_id, source="voice",
        metadata={"audio_events": audio_events} if audio_events else None,
    )
    audio_out = None
    if speak and turn.get("response"):
        audio_out = await services.voice.speak(turn["response"], voice)
    return ok({"transcript": transcript["text"], **turn, "audio": audio_out, "audio_events": audio_events},
              "Voice command processed")
