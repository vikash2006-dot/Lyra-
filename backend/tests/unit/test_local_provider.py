"""Unit tests for LYRA LocalProvider (Ollama runtime).

Tests runtime availability, model discovery, generation, streaming,
and multimodal formatting using pure mocks without requiring an installed local model.
"""

import io
import json
from unittest.mock import MagicMock, patch
import urllib.error

import pytest

from lyra.core.exceptions import (
    LocalModelNotFoundError,
    LocalProviderError,
    LocalRuntimeUnavailableError,
    ProviderResponseError,
    ProviderTimeoutError,
)
from lyra.models.capabilities import ProviderCapability
from lyra.models.messages import AIRequest, Message, Role
from lyra.models.multimodal import FilePart, ImagePart
from lyra.providers.local import LocalProvider, LocalProviderConfig


def test_local_provider_config_and_metadata():
    """Verify LocalProvider properties, capabilities, and configuration."""
    config = LocalProviderConfig(
        endpoint="http://127.0.0.1:11434",
        default_model="llama3.2:3b",
        timeout_seconds=45.0,
        auto_discover=True,
    )
    provider = LocalProvider(config=config)

    assert provider.name == "local"
    assert provider.endpoint == "http://127.0.0.1:11434"
    assert provider.default_model == "llama3.2:3b"
    assert provider.is_configured is True
    assert provider.supports_streaming is True
    assert provider.supports_vision is True
    assert provider.supports_files is True

    # Check capabilities
    assert provider.has_capability(ProviderCapability.TEXT_GENERATION)
    assert provider.has_capability(ProviderCapability.STREAMING)
    assert provider.has_capability(ProviderCapability.IMAGE_UNDERSTANDING)
    assert provider.has_capability(ProviderCapability.DOCUMENT_UNDERSTANDING)


def test_local_provider_runtime_unreachable():
    """Verify connection failure raises LocalRuntimeUnavailableError."""
    provider = LocalProvider(endpoint="http://127.0.0.1:99999", timeout=1.0)

    # Runtime availability check returns False
    with patch("urllib.request.urlopen", side_effect=urllib.error.URLError("Connection refused")):
        assert provider.is_runtime_available_sync() is False

        # Attempting generation raises LocalRuntimeUnavailableError
        req = AIRequest(messages=(Message(role=Role.USER, content="Hello"),))
        with pytest.raises(LocalRuntimeUnavailableError) as exc_info:
            provider.execute_sync(lambda: None) if False else None
            import asyncio
            asyncio.run(provider.generate(req))
        assert "unreachable or not running" in str(exc_info.value)


def test_local_provider_model_not_found():
    """Verify HTTP 404 from runtime raises LocalModelNotFoundError."""
    provider = LocalProvider(endpoint="http://localhost:11434", default_model="nonexistent-model")
    req = AIRequest(messages=(Message(role=Role.USER, content="Hello"),))

    mock_error = urllib.error.HTTPError(
        url="http://localhost:11434/api/chat",
        code=404,
        msg="Not Found",
        hdrs={},
        fp=io.BytesIO(b'{"error": "model nonexistent-model not found"}'),
    )

    with patch("urllib.request.urlopen", side_effect=mock_error):
        import asyncio
        with pytest.raises(LocalModelNotFoundError) as exc_info:
            asyncio.run(provider.generate(req))
        assert "not found on local runtime" in str(exc_info.value)


def test_local_provider_successful_generation():
    """Verify successful non-streaming response parsing."""
    provider = LocalProvider(endpoint="http://localhost:11434", default_model="llama3.2")
    req = AIRequest(
        messages=(Message(role=Role.USER, content="What is 2+2?"),),
        temperature=0.2,
    )

    mock_resp_payload = {
        "model": "llama3.2",
        "message": {
            "role": "assistant",
            "content": "2 + 2 = 4.",
        },
        "done": True,
        "prompt_eval_count": 12,
        "eval_count": 8,
    }

    mock_response = MagicMock()
    mock_response.read.return_value = json.dumps(mock_resp_payload).encode("utf-8")
    mock_response.__enter__.return_value = mock_response

    with patch("urllib.request.urlopen", return_value=mock_response):
        import asyncio
        response = asyncio.run(provider.generate(req))

    assert response.content == "2 + 2 = 4."
    assert response.model == "llama3.2"
    assert response.role == Role.ASSISTANT
    assert response.usage.prompt_tokens == 12
    assert response.usage.completion_tokens == 8
    assert response.usage.total_tokens == 20


def test_local_provider_streaming():
    """Verify token streaming from JSON-lines runtime response."""
    provider = LocalProvider(endpoint="http://localhost:11434", default_model="llama3.2")
    req = AIRequest(messages=(Message(role=Role.USER, content="Count to 3"),))

    stream_chunks = [
        json.dumps({"message": {"content": "1, "}, "done": False}).encode("utf-8") + b"\n",
        json.dumps({"message": {"content": "2, "}, "done": False}).encode("utf-8") + b"\n",
        json.dumps({"message": {"content": "3!"}, "done": True}).encode("utf-8") + b"\n",
    ]

    mock_response = MagicMock()
    mock_response.readline.side_effect = stream_chunks + [b""]

    with patch("urllib.request.urlopen", return_value=mock_response):
        async def _test():
            tokens = []
            async for token in provider.stream(req):
                tokens.append(token)
            return "".join(tokens)

        import asyncio
        result = asyncio.run(_test())

    assert result == "1, 2, 3!"


def test_local_provider_multimodal_payload_formatting():
    """Verify that images and files are correctly transformed for local runtime."""
    provider = LocalProvider(endpoint="http://localhost:11434", default_model="llama3.2-vision")

    image_part = ImagePart.from_bytes(b"\x89PNG\r\n\x1a\nfakeimage", mime_type="image/png")
    file_part = FilePart(filename="notes.txt", text_content="Sample document notes.")

    req = AIRequest(
        messages=(
            Message(
                role=Role.USER,
                content="Analyze this diagram and text:",
                parts=(image_part, file_part),
            ),
        )
    )

    payload = provider._build_payload(req, model="llama3.2-vision")
    assert payload["model"] == "llama3.2-vision"
    assert len(payload["messages"]) == 1
    user_msg = payload["messages"][0]
    assert user_msg["role"] == "user"
    assert "Analyze this diagram" in user_msg["content"]
    assert "Sample document notes." in user_msg["content"]
    assert "images" in user_msg
    assert len(user_msg["images"]) == 1
    assert user_msg["images"][0] == image_part.data_base64


def test_local_provider_model_discovery():
    """Verify listing available models and resolving active model without automatic downloads."""
    provider = LocalProvider(endpoint="http://localhost:11434", default_model="llama3.2")

    mock_tags_payload = {
        "models": [
            {"name": "llama3.2:latest", "model": "llama3.2:latest"},
            {"name": "qwen2.5:7b", "model": "qwen2.5:7b"},
            {"name": "mistral:latest", "model": "mistral:latest"},
        ]
    }

    mock_response = MagicMock()
    mock_response.read.return_value = json.dumps(mock_tags_payload).encode("utf-8")
    mock_response.__enter__.return_value = mock_response

    with patch("urllib.request.urlopen", return_value=mock_response):
        import asyncio
        models = asyncio.run(provider.list_available_models())
        selected = asyncio.run(provider.get_selected_model())

    assert models == ["llama3.2:latest", "qwen2.5:7b", "mistral:latest"]
    # Should resolve 'llama3.2' to 'llama3.2:latest'
    assert selected == "llama3.2:latest"
