"""xAI / Grok AI Provider implementation for LYRA."""

import asyncio
from collections.abc import AsyncIterator
import json
import socket
from typing import Any
import urllib.error
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
from lyra.providers.base import AIProvider

DEFAULT_XAI_MODEL = "grok-2-latest"
XAI_API_URL = "https://api.x.ai/v1/chat/completions"


class XAIProvider(AIProvider):
    """xAI (Grok) cloud AI provider adapter."""

    def __init__(
        self,
        api_key: str | None = None,
        default_model: str = DEFAULT_XAI_MODEL,
        timeout: float | None = None,
    ) -> None:
        settings = load_settings()
        self._api_key = api_key if api_key is not None else settings.xai_api_key
        self._default_model = default_model
        self._timeout = timeout if timeout is not None else settings.request_timeout_seconds

    @property
    def name(self) -> str:
        return "xai"

    @property
    def is_configured(self) -> bool:
        return bool(self._api_key and self._api_key.strip())

    @property
    def supports_vision(self) -> bool:
        return True

    @property
    def supports_streaming(self) -> bool:
        return True

    @property
    def supports_files(self) -> bool:
        return True

    def _build_payload(self, request: AIRequest, model: str, stream: bool = False) -> dict[str, Any]:
        """Convert canonical AIRequest into xAI OpenAI-compatible request payload."""
        from lyra.models.multimodal import FilePart, ImagePart

        messages: list[dict[str, Any]] = []

        if request.system_prompt:
            messages.append({"role": "system", "content": request.system_prompt})

        target_model = model

        for msg in request.messages:
            if msg.has_images():
                content_parts: list[dict[str, Any]] = []
                if msg.content:
                    content_parts.append({"type": "text", "text": msg.content})
                for part in getattr(msg, "parts", ()):
                    if isinstance(part, ImagePart):
                        content_parts.append({
                            "type": "image_url",
                            "image_url": {
                                "url": f"data:{part.mime_type};base64,{part.data_base64}"
                            },
                        })
                    elif isinstance(part, FilePart):
                        content_parts.append({
                            "type": "text",
                            "text": f"File [{part.filename}]:\n{part.text_content}",
                        })
                messages.append({
                    "role": msg.role.value,
                    "content": content_parts,
                })
            else:
                text_content = msg.content
                for part in getattr(msg, "parts", ()):
                    if isinstance(part, FilePart):
                        text_content += f"\n\nFile [{part.filename}]:\n{part.text_content}"
                messages.append({
                    "role": msg.role.value,
                    "content": text_content,
                })

        payload: dict[str, Any] = {
            "model": target_model,
            "messages": messages,
            "stream": stream,
        }

        if request.temperature is not None:
            payload["temperature"] = request.temperature
        if request.max_tokens is not None:
            payload["max_tokens"] = request.max_tokens

        return payload

    def _execute_http_request(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Execute synchronous HTTP request (invoked via asyncio.to_thread)."""
        data = json.dumps(payload).encode("utf-8")
        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json",
            "Authorization": f"Bearer {self._api_key}",
        }
        req = urllib.request.Request(XAI_API_URL, data=data, headers=headers, method="POST")

        try:
            with urllib.request.urlopen(req, timeout=self._timeout) as resp:
                raw_body = resp.read().decode("utf-8")
                return json.loads(raw_body)
        except urllib.error.HTTPError as http_err:
            raw_err = http_err.read().decode("utf-8", errors="replace")
            status = http_err.code
            if status in (401, 403):
                raise ProviderAuthenticationError(
                    f"xAI authentication failed (HTTP {status}): {raw_err}"
                ) from http_err
            if status == 429:
                err_lower = raw_err.lower()
                if "quota" in err_lower or "resource_exhausted" in err_lower:
                    raise ProviderQuotaExceededError(
                        f"xAI quota exhausted (HTTP 429): {raw_err}"
                    ) from http_err
                raise ProviderRateLimitError(
                    f"xAI rate limit exceeded (HTTP 429): {raw_err}"
                ) from http_err
            raise ProviderError(
                f"xAI API request failed with HTTP {status}: {raw_err}"
            ) from http_err
        except (urllib.error.URLError, socket.timeout, TimeoutError) as net_err:
            raise ProviderTimeoutError(
                f"xAI request timed out or connection failed: {net_err}"
            ) from net_err
        except json.JSONDecodeError as json_err:
            raise ProviderResponseError(
                f"xAI returned invalid JSON: {json_err}"
            ) from json_err

    async def generate(self, request: AIRequest) -> AIResponse:
        """Generate response via xAI / Grok Cloud REST API."""
        if not self.is_configured:
            raise ProviderNotConfiguredError(
                f"Provider '{self.name}' is NOT_CONFIGURED. Please set XAI_API_KEY."
            )

        model = request.model or self._default_model
        payload = self._build_payload(request, model, stream=False)

        response_data = await asyncio.to_thread(self._execute_http_request, payload)

        try:
            choices = response_data.get("choices")
            if not choices or not isinstance(choices, list):
                raise ProviderResponseError(
                    f"xAI response missing valid choices: {response_data}"
                )

            first_choice = choices[0]
            message_obj = first_choice.get("message", {})
            text_content = message_obj.get("content")
            if text_content is None or not isinstance(text_content, str):
                raise ProviderResponseError(
                    f"xAI response choice missing text content: {first_choice}"
                )

            finish_reason = first_choice.get("finish_reason")

            usage_obj = response_data.get("usage", {})
            usage: Usage | None = None
            if usage_obj and isinstance(usage_obj, dict):
                prompt_tokens = usage_obj.get("prompt_tokens")
                completion_tokens = usage_obj.get("completion_tokens")
                if isinstance(prompt_tokens, int) and isinstance(completion_tokens, int):
                    usage = Usage(
                        prompt_tokens=prompt_tokens,
                        completion_tokens=completion_tokens,
                        total_tokens=usage_obj.get("total_tokens", prompt_tokens + completion_tokens),
                    )

            actual_model = response_data.get("model", model)

            return AIResponse(
                content=text_content,
                model=actual_model,
                role=Role.ASSISTANT,
                finish_reason=finish_reason,
                usage=usage,
            )

        except (KeyError, TypeError) as err:
            raise ProviderResponseError(f"Malformed xAI response structure: {err}") from err

    async def stream(self, request: AIRequest) -> AsyncIterator[str]:
        """Stream response tokens from xAI / Grok via Server-Sent Events."""
        from lyra.providers.sse_stream import parse_openai_sse_line, sse_http_stream

        if not self.is_configured:
            raise ProviderNotConfiguredError(
                f"Provider '{self.name}' is NOT_CONFIGURED. Please set XAI_API_KEY."
            )

        model = request.model or self._default_model
        payload = self._build_payload(request, model, stream=True)
        headers = {
            "Authorization": f"Bearer {self._api_key}",
        }

        async for token in sse_http_stream(
            url=XAI_API_URL,
            payload=payload,
            headers=headers,
            timeout=self._timeout,
            parse_line_fn=parse_openai_sse_line,
        ):
            yield token

    async def health_check(self) -> bool:
        """Verify xAI provider availability and configuration status."""
        return self.is_configured
