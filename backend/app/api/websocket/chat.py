"""/ws/chat — streaming conversation with live task/tool status.

Client -> server:
  {"type": "message", "message": "...", "session_id": "optional"}
  {"type": "cancel"}                       stop the in-progress response/task
  {"type": "ping"}
Server -> client (all events carry "type" and "timestamp"):
  connected, message_received, thinking, task_started, task_update, tool_selected,
  tool_executing, tool_result, verifying, response_start, response_delta,
  completed, cancelled, error, pong
"""

from __future__ import annotations

import asyncio

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from app.api.websocket.common import Outbox, accept, error_event, parse_json
from app.core.errors import APIError
from app.services.events import make_event

router = APIRouter()


@router.websocket("/ws/chat")
async def chat_socket(websocket: WebSocket) -> None:
    services = await accept(websocket)
    if services is None:
        return
    outbox = Outbox(websocket)
    outbox.put(make_event("connected", channel="chat"))
    current: asyncio.Task | None = None

    async def run(message: str, session_id: str | None) -> None:
        try:
            services.limiter.check(f"ws:{id(websocket)}:chat")
            result = await services.chat.run_turn(message, session_id, emit=outbox.put, stream=True)
            if result.get("cancelled"):
                outbox.put(make_event("cancelled", session_id=result["session_id"], task_id=result.get("task_id")))
            else:
                outbox.put(make_event("completed", **result))
        except asyncio.CancelledError:
            outbox.put(make_event("cancelled", session_id=session_id))
        except Exception as err:
            outbox.put(error_event(err, session_id=session_id))

    try:
        while True:
            raw = await websocket.receive_text()
            data = parse_json(raw)
            if data is None:
                outbox.put(error_event(APIError("BAD_MESSAGE", "Invalid JSON message.")))
                continue
            kind = data.get("type")
            if kind == "ping":
                outbox.put(make_event("pong"))
            elif kind == "cancel":
                if current and not current.done():
                    current.cancel()
            elif kind == "message":
                if current and not current.done():
                    outbox.put(error_event(APIError("BUSY", "Please wait for the current response or stop it first.")))
                    continue
                message = str(data.get("message") or "")
                session_id = data.get("session_id") or None
                try:
                    services.chat.validate_message(message)
                    session = services.sessions.resolve(session_id)
                except APIError as err:
                    outbox.put(error_event(err))
                    continue
                outbox.put(make_event("message_received", session_id=session.session_id))
                current = asyncio.create_task(run(message, session.session_id))
            else:
                outbox.put(error_event(APIError("BAD_MESSAGE", f"Unknown message type '{kind}'.")))
    except WebSocketDisconnect:
        pass
    finally:
        if current and not current.done():
            current.cancel()
        await outbox.close()
