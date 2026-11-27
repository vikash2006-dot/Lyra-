"""/ws/voice — continuous voice conversation from the browser.

Client -> server:
  {"type": "start", "session_id": "optional", "speak": true, "voice": "optional"}
  <binary frame>   one complete utterance as WAV (16-bit PCM)
  {"type": "interrupt"}                     stop processing / speech synthesis
Server -> client:
  connected, voice_status {state: idle|transcribing|thinking|synthesizing},
  transcript {text, audio_events}, acknowledgement {text}, task_* / tool_* events,
  response {text, session_id, task_id}, audio {kind: ack|reply, mime_type, audio_base64},
  cancelled, error
Audio events (e.g. a detected cough) come from the raw clip, independent of the transcript.
"""

from __future__ import annotations

import asyncio

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from lyra.voice.models import CancellationToken

from app.api.websocket.common import Outbox, accept, error_event, parse_json
from app.core.errors import APIError
from app.services.events import make_event

router = APIRouter()


@router.websocket("/ws/voice")
async def voice_socket(websocket: WebSocket) -> None:
    services = await accept(websocket)
    if services is None:
        return
    outbox = Outbox(websocket)
    outbox.put(make_event("connected", channel="voice", voice=services.voice.status()))
    state = {"session_id": None, "speak": True, "voice": None}
    current: asyncio.Task | None = None
    tts_token: CancellationToken | None = None

    def status(value: str) -> None:
        outbox.put(make_event("voice_status", state=value, session_id=state["session_id"]))

    async def process(audio: bytes) -> None:
        nonlocal tts_token
        ack_task: asyncio.Task | None = None

        async def speak_ack(text: str) -> None:
            try:
                audio_out = await services.voice.speak(text, state["voice"], token=tts_token)
                if not tts_token.is_cancelled:
                    outbox.put(make_event("audio", kind="ack", **audio_out, session_id=state["session_id"]))
            except Exception:
                pass  # an acknowledgement is optional; never fail the turn over it

        def emit(event: dict) -> None:
            nonlocal ack_task
            outbox.put(event)
            if event.get("type") == "acknowledgement" and state["speak"] and ack_task is None:
                ack_task = asyncio.create_task(speak_ack(event["text"]))

        try:
            services.limiter.check(f"ws:{id(websocket)}:voice")
            services.voice.check_duplicate(audio)
            tts_token = CancellationToken()
            status("transcribing")
            transcript = await services.voice.transcribe(audio, services.config.max_audio_bytes)
            text = transcript["text"]
            audio_events = services.voice.analyze_audio(audio, state["session_id"])
            outbox.put(make_event("transcript", text=text, audio_events=audio_events, session_id=state["session_id"]))
            if not text:
                if audio_events:
                    reply = services.voice.cough_only_reply()
                    outbox.put(make_event("response", text=reply, session_id=state["session_id"], task_id=None,
                                          task=None, audio_events=audio_events))
                    if state["speak"]:
                        status("synthesizing")
                        audio_out = await services.voice.speak(reply, state["voice"], token=tts_token)
                        outbox.put(make_event("audio", kind="reply", **audio_out, session_id=state["session_id"]))
                status("idle")
                return
            status("thinking")
            result = await services.chat.run_turn(
                text, state["session_id"], emit=emit, source="voice",
                metadata={"audio_events": audio_events} if audio_events else None,
            )
            state["session_id"] = result["session_id"]
            if result.get("cancelled"):
                outbox.put(make_event("cancelled", session_id=state["session_id"]))
                status("idle")
                return
            outbox.put(make_event("response", text=result["response"], session_id=result["session_id"],
                                  task_id=result.get("task_id"), task=result.get("task")))
            if state["speak"] and result.get("response"):
                status("synthesizing")
                audio_out = await services.voice.speak(result["response"], state["voice"], token=tts_token)
                if ack_task is not None:
                    await ack_task  # the acknowledgement must be queued before the final reply
                if not tts_token.is_cancelled:
                    outbox.put(make_event("audio", kind="reply", **audio_out, session_id=state["session_id"]))
            status("idle")
        except asyncio.CancelledError:
            if ack_task:
                ack_task.cancel()
            outbox.put(make_event("cancelled", session_id=state["session_id"]))
            status("idle")
        except Exception as err:
            outbox.put(error_event(err, session_id=state["session_id"]))
            status("idle")

    try:
        while True:
            message = await websocket.receive()
            if message.get("type") == "websocket.disconnect":
                break
            if message.get("bytes") is not None:
                audio = message["bytes"]
                if current and not current.done():
                    outbox.put(error_event(APIError("BUSY", "Still processing the previous utterance.")))
                    continue
                try:
                    services.voice.validate_audio(audio, services.config.max_audio_bytes)
                except APIError as err:
                    outbox.put(error_event(err))
                    continue
                current = asyncio.create_task(process(audio))
                continue
            data = parse_json(message.get("text") or "")
            if data is None:
                outbox.put(error_event(APIError("BAD_MESSAGE", "Invalid JSON message.")))
                continue
            kind = data.get("type")
            if kind == "start":
                sid = data.get("session_id") or None
                if sid:
                    try:
                        services.sessions.get_record(sid)
                    except APIError as err:
                        outbox.put(error_event(err))
                        continue
                state.update(session_id=sid, speak=bool(data.get("speak", True)), voice=data.get("voice") or None)
                status("idle")
            elif kind == "interrupt":
                if tts_token:
                    tts_token.cancel()
                if current and not current.done():
                    current.cancel()
            elif kind == "ping":
                outbox.put(make_event("pong"))
            else:
                outbox.put(error_event(APIError("BAD_MESSAGE", f"Unknown message type '{kind}'.")))
    except WebSocketDisconnect:
        pass
    finally:
        if current and not current.done():
            current.cancel()
        await outbox.close()
