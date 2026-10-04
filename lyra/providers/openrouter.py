"""OpenRouter AI Provider implementation for LYRA."""

import asyncio
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
    ProviderRateLimitError,
    ProviderResponseError,
    ProviderTimeoutError,
)
from lyra.models.messages import AIRequest, AIResponse, Role, Usage
from lyra.providers.base import AIProvider

_UNSET = object()
DEFAULT_OPENROUTER_MODEL = "meta-llama/llama-3.3-70b-instruct:free"
FALLBACK_OPENROUTER_MODELS = ("google/gemma-4-31b-it:free", "google/gemini-2.0-flash-exp:free")
OPENROUTER_API_URL = "https://openrouter.ai/api/v1/chat/completions"


class OpenRouterProvider(AIProvider):
    """OpenRouter provider adapter supporting free tier models."""

    def __init__(
        self,
        api_key: Any = _UNSET,
        default_model: str = DEFAULT_OPENROUTER_MODEL,
        timeout: float | None = None,
    ) -> None:
        settings = load_settings()
        if api_key is _UNSET:
            self._api_key = settings.openrouter_api_key
        else:
            self._api_key = api_key
        self._default_model = default_model
        self._timeout = timeout if timeout is not None else settings.request_timeout_seconds

    @property
    def name(self) -> str:
        return "openrouter"

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

    def _build_payload(self, request: AIRequest, model: str) -> dict[str, Any]:
        """Convert canonical AIRequest into OpenRouter request payload."""
        from lyra.models.multimodal import FilePart, ImagePart

        messages: list[dict[str, Any]] = []

        if request.system_prompt:
            messages.append({"role": "system", "content": request.system_prompt})

        target_model = model
        if request.has_images() and (
            model == DEFAULT_OPENROUTER_MODEL
            or "free" in model.lower()
            or model in ("meta-llama/llama-3.3-70b-instruct:free", "google/gemma-4-31b-it:free")
        ):
            # Free tier multimodal model on OpenRouter
            target_model = "google/gemini-2.0-flash-exp:free"

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
            "HTTP-Referer": "https://github.com/lyra-ai/lyra",
            "X-Title": "LYRA Personal AI OS",
            "User-Agent": "LYRA-Personal-AI-OS/1.0 (Darwin; macOS)",
        }
        req = urllib.request.Request(OPENROUTER_API_URL, data=data, headers=headers, method="POST")

        try:
            with urllib.request.urlopen(req, timeout=self._timeout) as resp:
                raw_body = resp.read().decode("utf-8")
                return json.loads(raw_body)
        except urllib.error.HTTPError as http_err:
            raw_err = http_err.read().decode("utf-8", errors="replace")
            status = http_err.code
            if status == 404 and payload.get("model") == DEFAULT_OPENROUTER_MODEL:
                for alt in FALLBACK_OPENROUTER_MODELS:
                    alt_payload = dict(payload)
                    alt_payload["model"] = alt
                    try:
                        return self._execute_http_request(alt_payload)
                    except Exception:
                        continue
            if status in (401, 403):
                raise ProviderAuthenticationError(
                    f"OpenRouter authentication failed (HTTP {status}): {raw_err}"
                ) from http_err
            if status == 429:
                raise ProviderRateLimitError(
                    f"OpenRouter rate limit exceeded (HTTP 429): {raw_err}"
                ) from http_err
            raise ProviderError(
                f"OpenRouter API request failed with HTTP {status}: {raw_err}"
            ) from http_err
        except (urllib.error.URLError, socket.timeout, TimeoutError) as net_err:
            raise ProviderTimeoutError(
                f"OpenRouter request timed out or connection failed: {net_err}"
            ) from net_err
        except json.JSONDecodeError as json_err:
            raise ProviderResponseError(
                f"OpenRouter returned invalid JSON: {json_err}"
            ) from json_err

    async def generate(self, request: AIRequest) -> AIResponse:
        """Generate response via OpenRouter REST API."""
        if not self.is_configured:
            raise ProviderNotConfiguredError(
                f"Provider '{self.name}' is NOT_CONFIGURED. Please set OPENROUTER_API_KEY."
            )

        model = request.model or self._default_model
        payload = self._build_payload(request, model)

        response_data = await asyncio.to_thread(self._execute_http_request, payload)

        try:
            choices = response_data.get("choices")
            if not choices or not isinstance(choices, list):
                raise ProviderResponseError(
                    f"OpenRouter response missing valid choices: {response_data}"
                )

            first_choice = choices[0]
            message_obj = first_choice.get("message", {})
            text_content = message_obj.get("content")
            if text_content is None or not isinstance(text_content, str):
                raise ProviderResponseError(
                    f"OpenRouter response choice missing text content: {first_choice}"
                )

            finish_reason = first_choice.get("finish_reason")

            usage = None
            raw_usage = response_data.get("usage")
            if raw_usage and isinstance(raw_usage, dict):
                usage = Usage(
                    prompt_tokens=raw_usage.get("prompt_tokens", 0),
                    completion_tokens=raw_usage.get("completion_tokens", 0),
                    total_tokens=raw_usage.get("total_tokens", 0),
                )

            return AIResponse(
                content=text_content,
                model=model,
                role=Role.ASSISTANT,
                finish_reason=finish_reason,
                usage=usage,
                metadata={"provider": self.name},
            )
        except (KeyError, TypeError, IndexError) as err:
            raise ProviderResponseError(
                f"Malformed response structure from OpenRouter: {err}"
            ) from err

    async def stream(self, request: AIRequest):
        """Stream response tokens from OpenRouter via OpenAI-compatible SSE."""
        from lyra.providers.sse_stream import parse_openai_sse_line, sse_http_stream

        if not self.is_configured:
            raise ProviderNotConfiguredError(
                f"Provider '{self.name}' is NOT_CONFIGURED. Please set OPENROUTER_API_KEY."
            )

        model = request.model or self._default_model
        payload = self._build_payload(request, model)
        payload["stream"] = True

        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "HTTP-Referer": "https://github.com/lyra-ai/lyra",
            "X-Title": "LYRA Personal AI OS",
        }

        try:
            async for token in sse_http_stream(
                url=OPENROUTER_API_URL,
                payload=payload,
                headers=headers,
                timeout=self._timeout,
                parse_line_fn=parse_openai_sse_line,
            ):
                yield token
        except ProviderError as err:
            if "404" in str(err) and payload.get("model") == DEFAULT_OPENROUTER_MODEL:
                for alt in FALLBACK_OPENROUTER_MODELS:
                    payload["model"] = alt
                    try:
                        async for token in sse_http_stream(
                            url=OPENROUTER_API_URL,
                            payload=payload,
                            headers=headers,
                            timeout=self._timeout,
                            parse_line_fn=parse_openai_sse_line,
                        ):
                            yield token
                        return
                    except Exception:
                        continue
            raise

