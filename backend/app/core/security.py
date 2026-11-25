"""Access control and request throttling for the LYRA API.

* Optional shared access token (``LYRA_API_TOKEN``). When set, every HTTP request must
  send ``Authorization: Bearer <token>`` and every WebSocket must pass ``?token=<token>``.
  When unset, the server only listens on 127.0.0.1 by default, so it is reachable only
  from this machine.
* A small in-memory sliding-window rate limiter for expensive endpoints (chat, voice,
  uploads) to stop runaway clients from burning AI provider quota.
"""

from __future__ import annotations

from collections import defaultdict, deque
import hmac
import time

from fastapi import Request, WebSocket

from app.core.errors import APIError


def _token_matches(expected: str | None, provided: str | None) -> bool:
    if not expected:
        return True
    if not provided:
        return False
    return hmac.compare_digest(expected.encode(), provided.encode())


def check_http_token(request: Request, expected: str | None) -> None:
    if not expected:
        return
    header = request.headers.get("authorization", "")
    token = header[7:].strip() if header.lower().startswith("bearer ") else None
    if not _token_matches(expected, token):
        raise APIError("UNAUTHORIZED", "A valid API token is required.", 401)


def websocket_token_ok(websocket: WebSocket, expected: str | None) -> bool:
    return _token_matches(expected, websocket.query_params.get("token"))


def websocket_origin_ok(websocket: WebSocket, allowed_origins: tuple[str, ...]) -> bool:
    """Browsers always send Origin on WebSocket upgrades; reject foreign web pages.

    Non-browser clients (CLI tools, tests) do not send Origin and are allowed.
    """
    origin = websocket.headers.get("origin")
    if not origin:
        return True
    return "*" in allowed_origins or origin.rstrip("/") in allowed_origins


class RateLimiter:
    """Sliding-window limiter keyed by client and bucket name."""

    def __init__(self, per_minute: int) -> None:
        self.per_minute = per_minute
        self._hits: dict[str, deque[float]] = defaultdict(deque)

    def check(self, key: str) -> None:
        if self.per_minute <= 0:
            return
        now = time.monotonic()
        window = self._hits[key]
        while window and now - window[0] > 60.0:
            window.popleft()
        if len(window) >= self.per_minute:
            raise APIError("RATE_LIMITED", "Too many requests. Please slow down.", 429)
        window.append(now)
