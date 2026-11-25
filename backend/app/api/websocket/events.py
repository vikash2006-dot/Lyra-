"""/ws/events — global real-time feed: task_update events and notifications (reminders)."""

from __future__ import annotations

import asyncio
import json

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from app.api.websocket.common import accept
from app.services.events import make_event

router = APIRouter()


@router.websocket("/ws/events")
async def events_socket(websocket: WebSocket) -> None:
    services = await accept(websocket)
    if services is None:
        return
    queue = services.bus.subscribe()

    async def drain_client() -> None:
        # Consume (and ignore) client frames so disconnects are detected promptly.
        while True:
            msg = await websocket.receive()
            if msg.get("type") == "websocket.disconnect":
                return
            if msg.get("text") and '"ping"' in msg["text"]:
                await websocket.send_text(json.dumps(make_event("pong")))

    reader = asyncio.create_task(drain_client())
    try:
        await websocket.send_text(json.dumps(make_event("connected", channel="events")))
        while not reader.done():
            getter = asyncio.create_task(queue.get())
            done, _ = await asyncio.wait({getter, reader}, return_when=asyncio.FIRST_COMPLETED)
            if getter in done:
                await websocket.send_text(json.dumps(getter.result(), default=str))
            else:
                getter.cancel()
    except (WebSocketDisconnect, RuntimeError):
        pass
    finally:
        reader.cancel()
        services.bus.unsubscribe(queue)
