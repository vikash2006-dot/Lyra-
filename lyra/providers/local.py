"""Local AI Provider implementation for LYRA.

Enables offline and local AI capabilities via local model runtimes (such as Ollama)
using the standard LYRA AIProvider abstraction without external network calls.
"""

from collections.abc import AsyncIterator
from dataclasses import dataclass
import json
import socket
from typing import Any
import urllib.error
import urllib.request

from lyra.config.settings import Settings, load_settings
from lyra.core.exceptions import (
    LocalModelNotFoundError,
    LocalProviderError,
    LocalRuntimeUnavailableError,
    ProviderError,
    ProviderResponseError,
    ProviderTimeoutError,
)
from lyra.models.messages import AIRequest, AIResponse, Role, Usage
from lyra.observability.logging import get_logger
from lyra.providers.base import AIProvider

logger = get_logger("providers.local")

DEFAULT_LOCAL_ENDPOINT = "http://localhost:11434"
DEFAULT_LOCAL_MODEL = "llama3.2"
DEFAULT_LOCAL_TIMEOUT = 60.0


@dataclass(frozen=True)
class LocalProviderConfig:
    """Configuration for local AI provider runtime."""

    endpoint: str = DEFAULT_LOCAL_ENDPOINT
    default_model: str = DEFAULT_LOCAL_MODEL
    timeout_seconds: float = DEFAULT_LOCAL_TIMEOUT
    auto_discover: bool = True
    enabled: bool = True

    @classmethod
    def from_settings(cls, settings: Settings | None = None) -> "LocalProviderConfig":
        """Build LocalProviderConfig from active Settings."""
        s = settings or load_settings()
        return cls(
            endpoint=s.local_model_url.rstrip("/"),
            default_model=s.local_model_name,
            timeout_seconds=s.local_model_timeout_seconds,
            auto_discover=s.local_model_auto_discover,
            enabled=getattr(s, "local_provider_enabled", False),
        )


class LocalProvider(AIProvider):
    """Local AI provider adapter supporting Ollama and local model runtimes."""

    def __init__(
        self,
        config: LocalProviderConfig | None = None,
        endpoint: str | None = None,
        default_model: str | None = None,
        timeout: float | None = None,
        auto_discover: bool | None = None,
        enabled: bool | None = None,
    ) -> None:
        cfg = config or (LocalProviderConfig(endpoint=endpoint.rstrip("/")) if endpoint else LocalProviderConfig.from_settings())
        self._endpoint = (endpoint or cfg.endpoint).rstrip("/")
        self._default_model = default_model or cfg.default_model
        self._timeout = timeout if timeout is not None else cfg.timeout_seconds
        self._auto_discover = auto_discover if auto_discover is not None else cfg.auto_discover
        if enabled is not None:
            self._enabled = enabled
        elif config is not None:
            self._enabled = config.enabled
        elif endpoint is not None:
            self._enabled = True
        else:
            self._enabled = cfg.enabled

    @property
    def name(self) -> str:
        return "local"

    @property
    def endpoint(self) -> str:
        return self._endpoint

    @property
    def default_model(self) -> str:
        return self._default_model

    @property
    def is_configured(self) -> bool:
        """Local provider is configured when enabled and endpoint is provided."""
        return bool(self._enabled and self._endpoint)

    @property
    def supports_vision(self) -> bool:
        return True

    @property
    def supports_streaming(self) -> bool:
        return True

    @property
    def supports_files(self) -> bool:
        return True

    # -------------------------------------------------------------------------
    # Model Discovery & Inspection
    # -------------------------------------------------------------------------

    def is_runtime_available_sync(self, timeout: float = 1.5) -> bool:
        """Synchronously probe whether the local runtime is running and reachable."""
        url = f"{self._endpoint}/api/tags"
        req = urllib.request.Request(url, method="GET")
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return resp.status == 200
        except Exception:
            return False

    async def is_runtime_available(self, timeout: float = 1.5) -> bool:
        """Asynchronously probe whether the local runtime is running."""
        import asyncio
        return await asyncio.to_thread(self.is_runtime_available_sync, timeout)

    def list_available_models_sync(self) -> list[str]:
        """Synchronously query the local runtime for installed models."""
        url = f"{self._endpoint}/api/tags"
        req = urllib.request.Request(url, method="GET")
        try:
            with urllib.request.urlopen(req, timeout=self._timeout) as resp:
                raw_body = resp.read().decode("utf-8")
                data = json.loads(raw_body)
                models_data = data.get("models", [])
                return [m.get("name") for m in models_data if isinstance(m, dict) and "name" in m]
        except urllib.error.HTTPError as http_err:
            raise LocalProviderError(f"HTTP error querying local models: {http_err.code}") from http_err
        except (urllib.error.URLError, socket.timeout, TimeoutError) as net_err:
            raise LocalRuntimeUnavailableError(
                f"Local runtime at '{self._endpoint}' is unreachable: {net_err}"
            ) from net_err
        except json.JSONDecodeError as json_err:
            raise ProviderResponseError(f"Local runtime returned invalid JSON: {json_err}") from json_err

    async def list_available_models(self) -> list[str]:
        """Asynchronously query the local runtime for installed models."""
        import asyncio
        return await asyncio.to_thread(self.list_available_models_sync)

    def get_model_info_sync(self, model_name: str) -> dict[str, Any]:
        """Synchronously get metadata and capabilities for a specific local model."""
        url = f"{self._endpoint}/api/show"
        payload = json.dumps({"name": model_name}).encode("utf-8")
        req = urllib.request.Request(url, data=payload, headers={"Content-Type": "application/json"}, method="POST")
        try:
            with urllib.request.urlopen(req, timeout=self._timeout) as resp:
                raw_body = resp.read().decode("utf-8")
                return json.loads(raw_body)
        except urllib.error.HTTPError as http_err:
            if http_err.code == 404:
                raise LocalModelNotFoundError(
                    f"Model '{model_name}' not found on local runtime at '{self._endpoint}'."
                ) from http_err
            raise LocalProviderError(f"Failed to query model info: HTTP {http_err.code}") from http_err
        except (urllib.error.URLError, socket.timeout, TimeoutError) as net_err:
            raise LocalRuntimeUnavailableError(
                f"Local runtime at '{self._endpoint}' is unreachable: {net_err}"
            ) from net_err

    async def get_model_info(self, model_name: str) -> dict[str, Any]:
        """Asynchronously get metadata and capabilities for a specific local model."""
        import asyncio
        return await asyncio.to_thread(self.get_model_info_sync, model_name)

    async def get_selected_model(self) -> str:
        """Resolve active model name considering configuration and discovered models."""
        if not self._auto_discover:
            return self._default_model

        try:
            models = await self.list_available_models()
            if not models:
                return self._default_model

            # Check if default_model matches an installed model (e.g. 'llama3.2' in 'llama3.2:latest')
            for m in models:
                if m == self._default_model or m.startswith(f"{self._default_model}:"):
                    return m

            # Fall back to first installed model if default not present
            return models[0]
        except Exception:
            return self._default_model

    # -------------------------------------------------------------------------
    # Request Payload Formatting
    # -------------------------------------------------------------------------

    def _build_payload(self, request: AIRequest, model: str, stream: bool = False) -> dict[str, Any]:
        """Convert canonical AIRequest into Ollama-compatible chat completions payload."""
        from lyra.models.multimodal import FilePart, ImagePart

        messages: list[dict[str, Any]] = []

        if request.system_prompt:
            messages.append({"role": "system", "content": request.system_prompt})

        for msg in request.messages:
            role_str = msg.role.value if isinstance(msg.role, Role) else str(msg.role)
            # Ollama recognizes system, user, assistant
            if role_str == "tool":
                role_str = "user"

            msg_dict: dict[str, Any] = {
                "role": role_str,
                "content": msg.content or "",
            }

            # Multimodal images
            images: list[str] = []
            file_texts: list[str] = []

            for part in msg.parts:
                if isinstance(part, ImagePart):
                    # Ollama expects base64 encoded strings in 'images' list
                    images.append(part.data_base64)
                elif isinstance(part, FilePart):
                    file_texts.append(part.text_content)

            if images:
                msg_dict["images"] = images

            if file_texts:
                extra_content = "\n".join(file_texts)
                if msg_dict["content"]:
                    msg_dict["content"] = f"{msg_dict['content']}\n\n{extra_content}"
                else:
                    msg_dict["content"] = extra_content

            messages.append(msg_dict)

        payload: dict[str, Any] = {
            "model": model,
            "messages": messages,
            "stream": stream,
        }

        options: dict[str, Any] = {}
        if request.temperature is not None:
            options["temperature"] = request.temperature
        if request.max_tokens is not None:
            options["num_predict"] = request.max_tokens

        if options:
            payload["options"] = options

        return payload

    # -------------------------------------------------------------------------
    # Non-Streaming Execution
    # -------------------------------------------------------------------------

    def _execute_chat_request(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Synchronously execute chat request to local runtime endpoint."""
        url = f"{self._endpoint}/api/chat"
        data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            url,
            data=data,
            headers={"Content-Type": "application/json", "Accept": "application/json"},
            method="POST",
        )

        try:
            with urllib.request.urlopen(req, timeout=self._timeout) as resp:
                raw_body = resp.read().decode("utf-8")
                return json.loads(raw_body)
        except urllib.error.HTTPError as http_err:
            raw_err = http_err.read().decode("utf-8", errors="replace")
            status = http_err.code
            if status == 404:
                raise LocalModelNotFoundError(
                    f"Model '{payload.get('model')}' not found on local runtime at '{self._endpoint}'. "
                    f"Response: {raw_err}"
                ) from http_err
            raise LocalProviderError(
                f"Local model runtime error (HTTP {status}): {raw_err}"
            ) from http_err
        except (urllib.error.URLError, socket.timeout, TimeoutError, ConnectionRefusedError) as net_err:
            raise LocalRuntimeUnavailableError(
                f"Local AI runtime at '{self._endpoint}' is unreachable or not running: {net_err}"
            ) from net_err
        except json.JSONDecodeError as json_err:
            raise ProviderResponseError(
                f"Local AI runtime returned invalid JSON: {json_err}"
            ) from json_err

    async def generate(self, request: AIRequest) -> AIResponse:
        """Generate response via local AI runtime REST API."""
        import asyncio

        model = request.model or await self.get_selected_model()
        payload = self._build_payload(request, model, stream=False)

        response_data = await asyncio.to_thread(self._execute_chat_request, payload)

        message_data = response_data.get("message", {})
        content = message_data.get("content", "")
        role_str = message_data.get("role", "assistant")

        prompt_tokens = response_data.get("prompt_eval_count", 0)
        completion_tokens = response_data.get("eval_count", 0)

        return AIResponse(
            content=content,
            model=response_data.get("model", model),
            role=Role(role_str) if role_str in (r.value for r in Role) else Role.ASSISTANT,
            usage=Usage(
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
                total_tokens=prompt_tokens + completion_tokens,
            ),
            metadata={"raw_response": response_data},
        )

    # -------------------------------------------------------------------------
    # Streaming Execution
    # -------------------------------------------------------------------------

    async def stream(self, request: AIRequest) -> AsyncIterator[str]:
        """Stream response tokens from local AI runtime."""
        import asyncio

        model = request.model or await self.get_selected_model()
        payload = self._build_payload(request, model, stream=True)

        url = f"{self._endpoint}/api/chat"
        data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            url,
            data=data,
            headers={"Content-Type": "application/json", "Accept": "application/json"},
            method="POST",
        )

        def _open_stream():
            try:
                return urllib.request.urlopen(req, timeout=self._timeout)
            except urllib.error.HTTPError as http_err:
                raw_err = http_err.read().decode("utf-8", errors="replace")
                if http_err.code == 404:
                    raise LocalModelNotFoundError(
                        f"Model '{model}' not found on local runtime at '{self._endpoint}'. {raw_err}"
                    ) from http_err
                raise LocalProviderError(f"Local runtime HTTP {http_err.code}: {raw_err}") from http_err
            except (urllib.error.URLError, socket.timeout, TimeoutError, ConnectionRefusedError) as net_err:
                raise LocalRuntimeUnavailableError(
                    f"Local AI runtime at '{self._endpoint}' is unreachable: {net_err}"
                ) from net_err

        resp = await asyncio.to_thread(_open_stream)

        try:
            loop = asyncio.get_running_loop()
            while True:
                line = await loop.run_in_executor(None, resp.readline)
                if not line:
                    break
                line_str = line.decode("utf-8").strip()
                if not line_str:
                    continue
                try:
                    chunk = json.loads(line_str)
                except json.JSONDecodeError:
                    continue

                msg = chunk.get("message", {})
                delta = msg.get("content", "")
                if delta:
                    yield delta

                if chunk.get("done", False):
                    break
        finally:
            resp.close()
