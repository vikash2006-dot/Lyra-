"""Unit tests for multimodal payload translation and capability routing across providers."""

import pytest

from lyra.models.capabilities import ProviderCapability
from lyra.models.messages import AIRequest, Message, Role
from lyra.models.multimodal import AudioPart, FilePart, ImagePart
from lyra.providers.cerebras import CerebrasProvider
from lyra.providers.gemini import GeminiProvider
from lyra.providers.groq import GroqProvider
from lyra.providers.openrouter import OpenRouterProvider
from lyra.routing.health import ProviderHealthTracker
from lyra.routing.strategies import PriorityFallbackStrategy


def test_gemini_multimodal_payload_construction():
    gemini = GeminiProvider(api_key="mock-key")
    assert gemini.has_capability(ProviderCapability.IMAGE_UNDERSTANDING) is True
    assert gemini.has_capability(ProviderCapability.DOCUMENT_UNDERSTANDING) is True
    assert gemini.has_capability(ProviderCapability.AUDIO_UNDERSTANDING) is True

    img = ImagePart.from_bytes(b"pngdata", mime_type="image/png")
    aud = AudioPart.from_bytes(b"audiodata", mime_type="audio/wav")
    file_part = FilePart(filename="data.txt", text_content="column1,column2\n1,2")

    msg = Message(
        role=Role.USER,
        content="Analyze these multimodal items",
        parts=(img, aud, file_part),
    )
    req = AIRequest(messages=[msg])
    payload = gemini._build_payload(req)

    assert "contents" in payload
    parts = payload["contents"][0]["parts"]
    assert len(parts) == 4
    assert parts[0]["text"] == "Analyze these multimodal items"
    assert parts[1]["inline_data"]["mime_type"] == "image/png"
    assert parts[2]["inline_data"]["mime_type"] == "audio/wav"
    assert "File [data.txt]" in parts[3]["text"]


def test_groq_multimodal_payload_and_vision_model_switch():
    groq = GroqProvider(api_key="mock-key")
    assert groq.has_capability(ProviderCapability.IMAGE_UNDERSTANDING) is True
    assert groq.has_capability(ProviderCapability.AUDIO_UNDERSTANDING) is False

    img = ImagePart.from_bytes(b"jpgdata", mime_type="image/jpeg")
    msg = Message(
        role=Role.USER,
        content="What is this picture?",
        parts=(img,),
    )
    req = AIRequest(messages=[msg])
    payload = groq._build_payload(req, model="llama-3.3-70b-versatile")

    # Automatically switches to vision model when image is present
    assert payload["model"] == "llama-3.2-11b-vision-preview"
    msg_content = payload["messages"][0]["content"]
    assert isinstance(msg_content, list)
    assert msg_content[0]["type"] == "text"
    assert msg_content[1]["type"] == "image_url"
    assert "data:image/jpeg;base64," in msg_content[1]["image_url"]["url"]


def test_openrouter_multimodal_payload_construction():
    openrouter = OpenRouterProvider(api_key="mock-key")
    assert openrouter.has_capability(ProviderCapability.IMAGE_UNDERSTANDING) is True

    img = ImagePart.from_bytes(b"pngdata", mime_type="image/png")
    msg = Message(
        role=Role.USER,
        content="Describe this diagram",
        parts=(img,),
    )
    req = AIRequest(messages=[msg])
    payload = openrouter._build_payload(req, model="meta-llama/llama-3.3-70b-instruct:free")

    assert payload["model"] == "google/gemini-2.0-flash-exp:free"
    msg_content = payload["messages"][0]["content"]
    assert msg_content[1]["type"] == "image_url"


def test_cerebras_text_only_capability():
    cerebras = CerebrasProvider(api_key="mock-key")
    assert cerebras.has_capability(ProviderCapability.IMAGE_UNDERSTANDING) is False
    assert cerebras.has_capability(ProviderCapability.STREAMING) is True


def test_routing_strategy_filters_candidates_for_vision():
    gemini = GeminiProvider(api_key="gemini-key")
    cerebras = CerebrasProvider(api_key="cerebras-key")
    tracker = ProviderHealthTracker()

    strategy = PriorityFallbackStrategy(priority_order=["cerebras", "gemini"])

    img = ImagePart.from_bytes(b"pngdata", mime_type="image/png")
    vision_req = AIRequest(messages=[Message(role=Role.USER, content="look", parts=(img,))])

    # For vision requests, text-only Cerebras MUST be skipped even though it has higher priority
    candidates = strategy.select_candidates([cerebras, gemini], vision_req, tracker)
    assert len(candidates) == 1
    assert candidates[0].name == "gemini"

    # For regular text requests, Cerebras is included and ordered first
    text_req = AIRequest(messages=[Message(role=Role.USER, content="hello")])
    candidates_text = strategy.select_candidates([cerebras, gemini], text_req, tracker)
    assert len(candidates_text) == 2
    assert candidates_text[0].name == "cerebras"
