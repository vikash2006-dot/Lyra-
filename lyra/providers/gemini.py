"""Google Gemini AI Provider implementation for LYRA."""

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
    ProviderQuotaExceededError,
    ProviderRateLimitError,
    ProviderResponseError,
    ProviderTimeoutError,
)
from lyra.models.messages import AIRequest, AIResponse, Role, Usage
from lyra.observability.logging import sanitize_text
from lyra.providers.base import AIProvider

DEFAULT_GEMINI_MODEL = "gemini-2.5-flash"
GEMINI_BASE_URL = "https://generativelanguage.googleapis.com/v1beta/models"


_UNSET = object()


class GeminiProvider(AIProvider):
    """Google Gemini provider adapter using direct REST API."""

    def __init__(
        self,
        api_key: Any = _UNSET,
        default_model: str | None = None,
        timeout: float | None = None,
        base_url: str | None = None,
    ) -> None:
        settings = load_settings()
        if api_key is _UNSET:
            self._api_key = settings.gemini_api_key
        else:
            self._api_key = api_key
        self._default_model = (
            default_model
            or getattr(settings, "gemini_model", None)
            or DEFAULT_GEMINI_MODEL
        )
        self._timeout = timeout if timeout is not None else settings.request_timeout_seconds
        self._base_url = (
            base_url
            or getattr(settings, "gemini_base_url", None)
            or GEMINI_BASE_URL
        ).rstrip("/")

    @property
    def name(self) -> str:
        return "gemini"

    @property
    def is_configured(self) -> bool:
        return bool(self._api_key and self._api_key.strip())

    @property
    def supports_vision(self) -> bool:
        return True

    @property
    def supports_audio(self) -> bool:
        return True

    @property
    def supports_files(self) -> bool:
        return True

    @property
    def supports_streaming(self) -> bool:
        return True

    def _build_payload(self, request: AIRequest) -> dict[str, Any]:
        """Convert canonical AIRequest into Gemini generateContent JSON body."""
        from lyra.models.multimodal import AudioPart, FilePart, ImagePart

        contents: list[dict[str, Any]] = []
        system_instruction_text: str | None = request.system_prompt

        for msg in request.messages:
            if msg.role == Role.SYSTEM:
                # Append or set system instruction
                if system_instruction_text:
                    system_instruction_text += f"\n{msg.content}"
                else:
                    system_instruction_text = msg.content
            else:
                # Gemini role mapping: 'user' or 'model'
                gemini_role = "model" if msg.role == Role.ASSISTANT else "user"
                parts_list: list[dict[str, Any]] = []

                if msg.content:
                    parts_list.append({"text": msg.content})

                for part in getattr(msg, "parts", ()):
                    if isinstance(part, ImagePart):
                        parts_list.append({
                            "inline_data": {
                                "mime_type": part.mime_type,
                                "data": part.data_base64,
                            }
                        })
                    elif isinstance(part, AudioPart):
                        parts_list.append({
                            "inline_data": {
                                "mime_type": part.mime_type,
                                "data": part.data_base64,
                            }
                        })
                    elif isinstance(part, FilePart):
                        if part.data_base64:
                            parts_list.append({
                                "inline_data": {
                                "mime_type": part.mime_type,
                                "data": part.data_base64,
                            }
                        })
                        else:
                            parts_list.append({"text": f"File [{part.filename}]:\n{part.text_content}"})

                if not parts_list:
                    parts_list.append({"text": ""})

                contents.append({
                    "role": gemini_role,
                    "parts": parts_list,
                })

        # Ensure at least one content exists
        if not contents:
            contents.append({
                "role": "user",
                "parts": [{"text": system_instruction_text or ""}],
            })
            system_instruction_text = None

        payload: dict[str, Any] = {"contents": contents}

        if system_instruction_text:
            payload["systemInstruction"] = {
                "parts": [{"text": system_instruction_text}]
            }

        gen_config: dict[str, Any] = {}
        if request.temperature is not None:
            gen_config["temperature"] = request.temperature
        if request.max_tokens is not None:
            gen_config["maxOutputTokens"] = request.max_tokens
        if gen_config:
            payload["generationConfig"] = gen_config

        return payload

    def _execute_http_request(self, url: str, payload: dict[str, Any]) -> dict[str, Any]:
        """Execute synchronous HTTP request (invoked via asyncio.to_thread)."""
        data = json.dumps(payload).encode("utf-8")
        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json",
            "x-goog-api-key": str(self._api_key or ""),
        }
        req = urllib.request.Request(url, data=data, headers=headers, method="POST")

        try:
            with urllib.request.urlopen(req, timeout=self._timeout) as resp:
                raw_body = resp.read().decode("utf-8")
                return json.loads(raw_body)
        except urllib.error.HTTPError as http_err:
            raw_err = sanitize_text(http_err.read().decode("utf-8", errors="replace"))
            status = http_err.code
            is_quota = (
                status == 429
                or "RESOURCE_EXHAUSTED" in raw_err
                or "free_tier_requests" in raw_err
                or "quota" in raw_err.lower()
                or "rate limit" in raw_err.lower()
                or "rate_limit" in raw_err.lower()
            )
            if is_quota:
                raise ProviderQuotaExceededError(
                    f"Gemini quota exhausted (rate limit exceeded, HTTP {status}): {raw_err}"
                ) from http_err
            if status in (401, 403):
                raise ProviderAuthenticationError(
                    f"Gemini authentication failed (HTTP {status}): {raw_err}"
                ) from http_err
            raise ProviderError(
                f"Gemini API request failed with HTTP {status}: {raw_err}"
            ) from http_err
        except (urllib.error.URLError, socket.timeout, TimeoutError) as net_err:
            raise ProviderTimeoutError(
                f"Gemini request timed out or connection failed: {sanitize_text(str(net_err))}"
            ) from net_err
        except json.JSONDecodeError as json_err:
            raise ProviderResponseError(
                f"Gemini returned invalid JSON: {json_err}"
            ) from json_err

    async def generate(self, request: AIRequest) -> AIResponse:
        """Generate response via Google Gemini REST API."""
        if not self.is_configured:
            raise ProviderNotConfiguredError(
                f"Provider '{self.name}' is NOT_CONFIGURED. Please set GEMINI_API_KEY."
            )

        model = request.model or self._default_model
        url = f"{self._base_url}/{model}:generateContent?key={self._api_key}"
        payload = self._build_payload(request)

        response_data = await asyncio.to_thread(self._execute_http_request, url, payload)

        try:
            candidates = response_data.get("candidates")
            if not candidates or not isinstance(candidates, list):
                raise ProviderResponseError(
                    f"Gemini response missing valid candidates: {response_data}"
                )

            first_candidate = candidates[0]
            parts = first_candidate.get("content", {}).get("parts", [])
            if not parts or "text" not in parts[0]:
                raise ProviderResponseError(
                    f"Gemini candidate missing text parts: {first_candidate}"
                )

            text_content = parts[0]["text"]
            finish_reason = first_candidate.get("finishReason")

            # Extract token usage if available
            usage = None
            raw_usage = response_data.get("usageMetadata")
            if raw_usage and isinstance(raw_usage, dict):
                usage = Usage(
                    prompt_tokens=raw_usage.get("promptTokenCount", 0),
                    completion_tokens=raw_usage.get("candidatesTokenCount", 0),
                    total_tokens=raw_usage.get("totalTokenCount", 0),
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
                f"Malformed response structure from Gemini: {err}"
            ) from err

    async def stream(self, request: AIRequest):
        """Stream response tokens from Google Gemini via SSE."""
        from lyra.providers.sse_stream import sse_http_stream

        if not self.is_configured:
            raise ProviderNotConfiguredError(
                f"Provider '{self.name}' is NOT_CONFIGURED. Please set GEMINI_API_KEY."
            )

        model = request.model or self._default_model
        url = f"{self._base_url}/{model}:streamGenerateContent?alt=sse&key={self._api_key}"
        payload = self._build_payload(request)

        def _parse_line(line: str) -> str | None:
            if line.startswith("data:"):
                raw_json = line[5:].strip()
                if not raw_json:
                    return None
                try:
                    parsed = json.loads(raw_json)
                    candidates = parsed.get("candidates", [])
                    if candidates:
                        parts = candidates[0].get("content", {}).get("parts", [])
                        if parts and "text" in parts[0]:
                            return parts[0]["text"]
                except json.JSONDecodeError:
                    pass
            return None

        headers = {
            "x-goog-api-key": str(self._api_key or ""),
        }
        async for token in sse_http_stream(
            url=url,
            payload=payload,
            headers=headers,
            timeout=self._timeout,
            parse_line_fn=_parse_line,
        ):
            yield token

