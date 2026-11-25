"""In-process publish/subscribe bus for real-time events (task updates, notifications)."""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import Any


def utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def make_event(event_type: str, **payload: Any) -> dict[str, Any]:
    """Standard event envelope shared by every WebSocket channel."""
    return {"type": event_type, "timestamp": utc_iso(), **payload}


class EventBus:
    def __init__(self, max_queue: int = 500) -> None:
        self._subscribers: set[asyncio.Queue[dict[str, Any]]] = set()
        self._max_queue = max_queue

    def subscribe(self) -> asyncio.Queue[dict[str, Any]]:
        queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue(maxsize=self._max_queue)
        self._subscribers.add(queue)
        return queue

    def unsubscribe(self, queue: asyncio.Queue[dict[str, Any]]) -> None:
        self._subscribers.discard(queue)

    @property
    def subscriber_count(self) -> int:
        return len(self._subscribers)

    def publish(self, event: dict[str, Any]) -> None:
        for queue in list(self._subscribers):
            try:
                queue.put_nowait(event)
            except asyncio.QueueFull:
                # Slow consumer: drop its oldest event rather than blocking LYRA.
                try:
                    queue.get_nowait()
                    queue.put_nowait(event)
                except (asyncio.QueueEmpty, asyncio.QueueFull):
                    pass
