"""Anakin AI Provider implementation for LYRA.

Integrates Anakin AI as an execution and text-generation provider supporting
both Quick Apps and Chatbots, dynamic input structures, streaming tokens,
bounded exponential backoff retries, and comprehensive error mapping.
"""

import asyncio
from collections.abc import AsyncIterator
import json
import logging
import socket
import time
from typing import Any
import urllib.error
import urllib.parse
import urllib.request

from lyra.config.settings import load_settings
from lyra.core.exceptions import (
    ProviderAuthenticationError,
    ProviderError,
    ProviderNotConfiguredError,
    ProviderQuotaExceededError,
    ProviderRateLimitError,
    ProviderResponseError,
    ProviderTimeoutError,
)
from lyra.models.messages import AIRequest, AIResponse, Role, Usage
from lyra.observability.logging import get_logger, sanitize_text
from lyra.providers.base import AIProvider

logger = get_logger("providers.anakin")
_UNSET = object()

DEFAULT_ANAKIN_API_VERSION = "2024-05-06"
DEFAULT_ANAKIN_BASE_URL = "https://api.anakin.ai"
DEFAULT_ANAKIN_APP_TYPE = "quickapp"
MAX_RETRIES = 2
BACKOFF_BASE = 0.5


def _mask_api_key(key: str | None) -> str:
    """Mask API key for safe debugging without exposing secrets."""
    if not key:
        return "<none>"
    stripped = key.strip()
    if len(stripped) <= 8:
        return "***"
    return f"{stripped[:4]}...{stripped[-4:]}"


class AnakinClient:
    """Clean HTTP client for interacting with the Anakin AI REST API."""

    def __init__(
        self,
        api_key: str,
        api_version: str = DEFAULT_ANAKIN_API_VERSION,
        base_url: str = DEFAULT_ANAKIN_BASE_URL,
        timeout: float = 30.0,
    ) -> None:
        self.api_key = api_key
        self.api_version = api_version
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout

    def _get_headers(self) -> dict[str, str]:
        """Construct secure authorization and metadata headers."""
        return {
            "Authorization": f"Bearer {self.api_key}",
            "X-Anakin-Api-Version": self.api_version,
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
            "User-Agent": "LYRA-Personal-AI-OS/1.0 (Darwin; macOS)",
        }

    def _execute_http(
        self,
        method: str,
        endpoint: str,
        payload: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Synchronously execute HTTP request with bounded exponential backoff retries."""
        url = f"{self.base_url}/{endpoint.lstrip('/')}"
        data = json.dumps(payload).encode("utf-8") if payload is not None else None
        headers = self._get_headers()

        last_error: Exception | None = None

        for attempt in range(MAX_RETRIES + 1):
            req = urllib.request.Request(url, data=data, headers=headers, method=method)
            try:
                with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                    raw_body = resp.read().decode("utf-8", errors="replace")
                    if not raw_body.strip():
                        return {"success": True}
                    try:
                        return json.loads(raw_body)
                    except json.JSONDecodeError as json_err:
                        raise ProviderResponseError(
                            f"Anakin returned invalid JSON response: {json_err}"
                        ) from json_err

            except urllib.error.HTTPError as http_err:
                raw_err = http_err.read().decode("utf-8", errors="replace")
                status = http_err.code

                # Authentication failures: do NOT retry
                if status in (401, 403):
                    raise ProviderAuthenticationError(
                        f"Anakin authentication failed (HTTP {status}): {raw_err}"
                    ) from http_err

                # Rate limiting / quota errors: do NOT retry
                if status == 429:
                    if "quota" in raw_err.lower() or "credits" in raw_err.lower():
                        raise ProviderQuotaExceededError(
                            f"Anakin quota/credits exhausted (HTTP 429): {raw_err}"
                        ) from http_err
                    raise ProviderRateLimitError(
                        f"Anakin rate limit exceeded (HTTP 429): {raw_err}"
                    ) from http_err

                # Server errors: retryable
                if status in (500, 502, 503, 504) and attempt < MAX_RETRIES:
                    backoff = BACKOFF_BASE * (2**attempt)
                    logger.warning(
                        "Anakin server error (HTTP %d). Retrying in %.2fs (attempt %d/%d)...",
                        status,
                        backoff,
                        attempt + 1,
                        MAX_RETRIES,
                    )
                    time.sleep(backoff)
                    last_error = http_err
                    continue

                raise ProviderError(
                    f"Anakin API request failed with HTTP {status}: {raw_err}"
                ) from http_err

            except (urllib.error.URLError, socket.timeout, TimeoutError) as net_err:
                if attempt < MAX_RETRIES:
                    backoff = BACKOFF_BASE * (2**attempt)
                    logger.warning(
                        "Anakin network error: %s. Retrying in %.2fs (attempt %d/%d)...",
                        net_err,
                        backoff,
                        attempt + 1,
                        MAX_RETRIES,
                    )
                    time.sleep(backoff)
                    last_error = net_err
                    continue
                raise ProviderTimeoutError(
                    f"Anakin request timed out or connection failed after {MAX_RETRIES + 1} attempts: {net_err}"
                ) from net_err

        if last_error:
            raise ProviderError(f"Anakin request failed: {last_error}") from last_error
        raise ProviderError("Anakin request terminated unexpectedly.")

    async def run_quickapp(
        self,
        app_id: str,
        inputs: dict[str, Any],
        stream: bool = False,
    ) -> dict[str, Any]:
        """Execute an Anakin Quick App run asynchronously."""
        endpoint = f"v1/quickapps/{app_id}/runs"
        payload = {"inputs": inputs, "stream": stream}
        return await asyncio.to_thread(self._execute_http, "POST", endpoint, payload)

    async def run_chatbot(
        self,
        app_id: str,
        content: str,
        conversation_id: str | None = None,
        stream: bool = False,
    ) -> dict[str, Any]:
        """Send message to an Anakin Chatbot application asynchronously."""
        endpoint = f"v1/chatbots/{app_id}/messages"
        payload: dict[str, Any] = {"content": content, "stream": stream}
        if conversation_id:
            payload["conversation_id"] = conversation_id
        return await asyncio.to_thread(self._execute_http, "POST", endpoint, payload)

    async def get_run_status(self, app_id: str, run_id: str) -> dict[str, Any]:
        """Fetch the status and results of a Quick App run."""
        endpoint = f"v1/quickapps/{app_id}/runs/{run_id}"
        return await asyncio.to_thread(self._execute_http, "GET", endpoint, None)

    def stream_sse_sync(
        self,
        endpoint: str,
        payload: dict[str, Any],
    ) -> list[str]:
        """Stream Server-Sent Events synchronously from Anakin and return collected text tokens."""
        url = f"{self.base_url}/{endpoint.lstrip('/')}"
        data = json.dumps(payload).encode("utf-8")
        headers = self._get_headers()
        req = urllib.request.Request(url, data=data, headers=headers, method="POST")

        tokens: list[str] = []
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                for raw_line in resp:
                    line = raw_line.decode("utf-8", errors="replace").strip()
                    if not line:
                        continue
                    if line.startswith("data:"):
                        content = line[5:].strip()
                        if content == "[DONE]":
                            break
                        try:
                            parsed = json.loads(content)
                            token = (
                                parsed.get("text")
                                or parsed.get("delta")
                                or parsed.get("content")
                                or parsed.get("result")
                                or ""
                            )
                            if token:
                                tokens.append(str(token))
                        except json.JSONDecodeError:
                            if content:
                                tokens.append(content)
        except urllib.error.HTTPError as http_err:
            raw_err = http_err.read().decode("utf-8", errors="replace")
            status = http_err.code
            if status in (401, 403):
                raise ProviderAuthenticationError(
                    f"Anakin authentication failed (HTTP {status}): {raw_err}"
                ) from http_err
            if status == 429:
                raise ProviderRateLimitError(
                    f"Anakin rate limit exceeded (HTTP 429): {raw_err}"
                ) from http_err
            raise ProviderError(f"Anakin streaming failed (HTTP {status}): {raw_err}") from http_err
        except Exception as err:
            raise ProviderError(f"Anakin SSE streaming error: {err}") from err

        return tokens


class AnakinProvider(AIProvider):
    """Anakin AI provider adapter for LYRA."""

    def __init__(
        self,
        api_key: Any = _UNSET,
        app_id: Any = _UNSET,
        api_version: str | None = None,
        base_url: str | None = None,
        app_type: str | None = None,
        timeout: float | None = None,
    ) -> None:
        settings = load_settings()
        self._api_key = settings.anakin_api_key if api_key is _UNSET else api_key
        self._app_id = settings.anakin_app_id if app_id is _UNSET else app_id
        self._api_version = api_version or settings.anakin_api_version
        self._base_url = (base_url or settings.anakin_base_url).rstrip("/")
        self._app_type = (app_type or settings.anakin_app_type).lower().strip()
        self._timeout = timeout if timeout is not None else settings.request_timeout_seconds

        self._client: AnakinClient | None = None
        if self._api_key:
            self._client = AnakinClient(
                api_key=self._api_key,
                api_version=self._api_version,
                base_url=self._base_url,
                timeout=self._timeout,
            )

    @property
    def name(self) -> str:
        return "anakin"

    @property
    def is_configured(self) -> bool:
        return bool(self._api_key and str(self._api_key).strip())

    @property
    def supports_streaming(self) -> bool:
        return True

    @property
    def supports_files(self) -> bool:
        return True

    @property
    def supports_vision(self) -> bool:
        return False

    @property
    def client(self) -> AnakinClient:
        if not self._client:
            if not self.is_configured:
                raise ProviderNotConfiguredError(
                    f"Provider '{self.name}' is NOT_CONFIGURED. Please set ANAKIN_API_KEY in .env."
                )
            self._client = AnakinClient(
                api_key=str(self._api_key),
                api_version=self._api_version,
                base_url=self._base_url,
                timeout=self._timeout,
            )
        return self._client

    def _extract_user_prompt(self, request: AIRequest) -> str:
        """Extract user input text and system instructions from AIRequest."""
        prompt_parts: list[str] = []
        if request.system_prompt:
            prompt_parts.append(f"Instructions: {request.system_prompt}")

        for msg in request.messages:
            if msg.role == Role.USER and msg.content:
                prompt_parts.append(msg.content)
            elif msg.content:
                prompt_parts.append(f"{msg.role.value}: {msg.content}")

        return "\n\n".join(prompt_parts) if prompt_parts else "Hello"

    def _build_quickapp_inputs(self, request: AIRequest, prompt: str) -> dict[str, Any]:
        """Construct dynamic inputs dictionary for Anakin Quick App execution."""
        meta_inputs = request.metadata.get("inputs")
        if isinstance(meta_inputs, dict):
            return dict(meta_inputs)

        # Dynamic multi-key mapping so different Anakin templates find their expected input field
        return {
            "input": prompt,
            "prompt": prompt,
            "query": prompt,
            "content": prompt,
            "text": prompt,
            "topic": prompt,
        }

    def _extract_response_text(self, data: dict[str, Any]) -> str:
        """Extract the synthesized response text from varied Anakin response schemas."""
        if not isinstance(data, dict):
            return str(data)

        # 1. Check direct string fields
        for field_name in ("result", "output", "answer", "content", "response", "text"):
            val = data.get(field_name)
            if isinstance(val, str) and val.strip():
                return val.strip()

        # 2. Check OpenAI-like choices
        choices = data.get("choices")
        if isinstance(choices, list) and choices:
            first = choices[0]
            if isinstance(first, dict):
                msg = first.get("message", {})
                if isinstance(msg, dict) and msg.get("content"):
                    return str(msg["content"]).strip()
                if first.get("text"):
                    return str(first["text"]).strip()

        # 3. Check nested result / data dict
        for container_key in ("data", "result", "output"):
            nested = data.get(container_key)
            if isinstance(nested, dict):
                for sub_key in ("content", "text", "answer", "output", "result"):
                    sub_val = nested.get(sub_key)
                    if isinstance(sub_val, str) and sub_val.strip():
                        return sub_val.strip()

        # 4. Check for completed run with status
        if data.get("status") in ("COMPLETED", "SUCCESS") and data.get("id"):
            return f"Anakin workflow completed (ID: {data['id']})."

        # Raise ProviderResponseError on malformed / unrecognized payload
        raise ProviderResponseError(f"Anakin returned unrecognized response structure: {data}")

    async def generate(self, request: AIRequest) -> AIResponse:
        """Execute Anakin AI request for Quick App or Chatbot."""
        if not self.is_configured:
            raise ProviderNotConfiguredError(
                f"Provider '{self.name}' is NOT_CONFIGURED. Please configure ANAKIN_API_KEY."
            )

        app_id = (
            request.metadata.get("app_id")
            or request.metadata.get("anakin_app_id")
            or self._app_id
        )
        if not app_id:
            # If no specific App ID configured, use request model or raise clear guidance
            app_id = request.model or getattr(self, "_app_id", None)

        if not app_id or app_id == self.name:
            # If no specific app is defined, return informative provider assistance
            app_id = "default"

        app_type = (
            request.metadata.get("app_type")
            or request.metadata.get("anakin_app_type")
            or self._app_type
        ).lower()

        prompt = self._extract_user_prompt(request)
        client = self.client

        start_time = time.time()
        logger.info(
            "Dispatching Anakin AI request (app_id: %s, app_type: %s, prompt_len: %d)",
            app_id,
            app_type,
            len(prompt),
        )

        try:
            if app_type == "chatbot":
                conv_id = request.metadata.get("conversation_id") or request.metadata.get("session_id")
                data = await client.run_chatbot(
                    app_id=str(app_id),
                    content=prompt,
                    conversation_id=str(conv_id) if conv_id else None,
                    stream=False,
                )
            else:
                inputs = self._build_quickapp_inputs(request, prompt)
                data = await client.run_quickapp(
                    app_id=str(app_id),
                    inputs=inputs,
                    stream=False,
                )

            text_content = self._extract_response_text(data)

            return AIResponse(
                content=text_content,
                model=f"anakin-{app_id}",
                role=Role.ASSISTANT,
                finish_reason="stop",
                usage=Usage(prompt_tokens=len(prompt.split()), completion_tokens=len(text_content.split())),
                metadata={
                    "provider": self.name,
                    "app_id": str(app_id),
                    "app_type": app_type,
                    "raw_response": data,
                },
            )

        except (ProviderError, ProviderAuthenticationError, ProviderRateLimitError, ProviderQuotaExceededError):
            raise
        except Exception as err:
            clean_err = sanitize_text(str(err))
            raise ProviderError(f"Anakin AI execution error: {clean_err}") from err

    async def stream(self, request: AIRequest) -> AsyncIterator[str]:
        """Stream token deltas from Anakin via SSE or progressive token emission."""
        if not self.is_configured:
            raise ProviderNotConfiguredError(
                f"Provider '{self.name}' is NOT_CONFIGURED. Please set ANAKIN_API_KEY."
            )

        app_id = (
            request.metadata.get("app_id")
            or request.metadata.get("anakin_app_id")
            or self._app_id
            or "default"
        )
        app_type = (
            request.metadata.get("app_type")
            or request.metadata.get("anakin_app_type")
            or self._app_type
        ).lower()

        prompt = self._extract_user_prompt(request)
        client = self.client

        if app_type == "chatbot":
            endpoint = f"v1/chatbots/{app_id}/messages"
            conv_id = request.metadata.get("conversation_id")
            payload: dict[str, Any] = {"content": prompt, "stream": True}
            if conv_id:
                payload["conversation_id"] = conv_id
        else:
            endpoint = f"v1/quickapps/{app_id}/runs"
            inputs = self._build_quickapp_inputs(request, prompt)
            payload = {"inputs": inputs, "stream": True}

        try:
            tokens = await asyncio.to_thread(client.stream_sse_sync, endpoint, payload)
        except Exception:
            tokens = []

        if tokens:
            for tok in tokens:
                yield tok
        else:
            # Fallback to non-streaming generate if stream returned empty tokens
            resp = await self.generate(request)
            yield resp.content

    async def health_check(self) -> bool:
        """Verify Anakin provider configuration and availability."""
        return self.is_configured
