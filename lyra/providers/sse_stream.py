"""Standard library SSE (Server-Sent Events) streaming helper for AI providers."""

import asyncio
import json
import queue
import socket
import threading
from typing import Any, AsyncIterator, Callable
import urllib.error
import urllib.request

from lyra.core.exceptions import (
    ProviderAuthenticationError,
    ProviderError,
    ProviderQuotaExceededError,
    ProviderRateLimitError,
    ProviderResponseError,
    ProviderTimeoutError,
)
from lyra.observability.logging import sanitize_text

_SENTINEL = object()


def _stream_worker(
    req: urllib.request.Request,
    timeout: float,
    out_queue: queue.Queue[Any],
    parse_line_fn: Callable[[str], str | None],
) -> None:
    """Worker thread that executes blocking streaming HTTP request and puts tokens into queue."""
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            buffer = ""
            for raw_line in resp:
                decoded = raw_line.decode("utf-8", errors="replace")
                buffer += decoded
                while "\n" in buffer:
                    line, buffer = buffer.split("\n", 1)
                    line = line.strip()
                    if not line:
                        continue
                    token = parse_line_fn(line)
                    if token:
                        out_queue.put(token)
    except urllib.error.HTTPError as http_err:
        raw_err = sanitize_text(http_err.read().decode("utf-8", errors="replace"))
        status = http_err.code
        is_quota = (
            status == 429
            or "RESOURCE_EXHAUSTED" in raw_err
            or "free_tier_requests" in raw_err
            or "quota" in raw_err.lower()
        )
        if is_quota:
            out_queue.put(ProviderQuotaExceededError(f"Quota exceeded (HTTP {status}): {raw_err}"))
        elif status in (401, 403):
            out_queue.put(ProviderAuthenticationError(f"Authentication failed (HTTP {status}): {raw_err}"))
        else:
            out_queue.put(ProviderError(f"API request failed with HTTP {status}: {raw_err}"))
    except (urllib.error.URLError, socket.timeout, TimeoutError) as net_err:
        out_queue.put(ProviderTimeoutError(f"Request timed out or connection failed: {sanitize_text(str(net_err))}"))
    except Exception as err:
        out_queue.put(ProviderError(f"Streaming error: {sanitize_text(str(err))}"))
    finally:
        out_queue.put(_SENTINEL)


async def sse_http_stream(
    url: str,
    payload: dict[str, Any],
    headers: dict[str, str],
    timeout: float,
    parse_line_fn: Callable[[str], str | None],
) -> AsyncIterator[str]:
    """Execute an SSE streaming request and asynchronously yield text tokens."""
    data = json.dumps(payload).encode("utf-8")
    full_headers = {
        "Content-Type": "application/json",
        "Accept": "text/event-stream",
        "User-Agent": "LYRA-Personal-AI-OS/1.0 (Darwin; macOS)",
    }
    full_headers.update(headers)
    req = urllib.request.Request(url, data=data, headers=full_headers, method="POST")

    out_queue: queue.Queue[Any] = queue.Queue()
    thread = threading.Thread(
        target=_stream_worker,
        args=(req, timeout, out_queue, parse_line_fn),
        daemon=True,
    )
    thread.start()

    while True:
        try:
            # Poll non-blocking with small sleep to yield control to event loop
            item = out_queue.get_nowait()
        except queue.Empty:
            await asyncio.sleep(0.01)
            continue

        if item is _SENTINEL:
            break
        if isinstance(item, Exception):
            raise item
        yield str(item)


def parse_openai_sse_line(line: str) -> str | None:
    """Extract token text from an OpenAI-compatible SSE data line."""
    if line.startswith("data:"):
        raw_json = line[5:].strip()
        if not raw_json or raw_json == "[DONE]":
            return None
        try:
            parsed = json.loads(raw_json)
            choices = parsed.get("choices", [])
            if choices:
                delta = choices[0].get("delta", {})
                return delta.get("content")
        except json.JSONDecodeError:
            pass
    return None

