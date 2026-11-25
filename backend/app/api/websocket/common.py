"""Shared WebSocket plumbing: auth/origin checks and an ordered outbound queue."""

from __future__ import annotations

import asyncio
import json
from typing import Any

from fastapi import WebSocket
from starlette.websockets import WebSocketDisconnect, WebSocketState

from app.core.errors import APIError
from app.core.security import websocket_origin_ok, websocket_token_ok
from app.services.container import AppServices
from app.services.events import make_event

MAX_TEXT_FRAME = 64 * 1024


async def accept(websocket: WebSocket) -> AppServices | None:
    services: AppServices = websocket.app.state.services
    if not websocket_origin_ok(websocket, services.config.cors_origins) or not websocket_token_ok(
        websocket, services.config.api_token
    ):
        await websocket.close(code=4401, reason="Unauthorized")
        return None
    await websocket.accept()
    return services


class Outbox:
    """Serialises all outbound events for one socket through a single sender task."""

    def __init__(self, websocket: WebSocket) -> None:
        self.ws = websocket
        self.queue: asyncio.Queue[dict[str, Any] | None] = asyncio.Queue()
        self._task = asyncio.create_task(self._pump())

    def put(self, event: dict[str, Any]) -> None:
        self.queue.put_nowait(event)

    async def _pump(self) -> None:
        while True:
            event = await self.queue.get()
            if event is None:
                return
            if self.ws.application_state != WebSocketState.CONNECTED:
                return
            try:
                await self.ws.send_text(json.dumps(event, default=str))
            except (WebSocketDisconnect, RuntimeError):
                return

    async def close(self) -> None:
        self.queue.put_nowait(None)
        try:
            await asyncio.wait_for(self._task, timeout=2)
        except (asyncio.TimeoutError, asyncio.CancelledError):
            self._task.cancel()


def error_event(err: Exception, **extra: Any) -> dict[str, Any]:
    if isinstance(err, APIError):
        return make_event("error", error={"code": err.code, "message": err.message}, **extra)
    return make_event("error", error={"code": "INTERNAL_ERROR", "message": "An unexpected error occurred."}, **extra)


def parse_json(raw: str) -> dict[str, Any] | None:
    if len(raw) > MAX_TEXT_FRAME:
        return None
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return None
    return data if isinstance(data, dict) else None
