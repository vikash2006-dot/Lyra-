"""Provider capability taxonomy and detection for LYRA."""

from enum import Enum


class ProviderCapability(str, Enum):
    """Enumeration of provider capabilities for intelligent routing and validation."""

    TEXT_GENERATION = "text_generation"
    STREAMING = "streaming"
    IMAGE_UNDERSTANDING = "image_understanding"
    DOCUMENT_UNDERSTANDING = "document_understanding"
    AUDIO_UNDERSTANDING = "audio_understanding"

    @classmethod
    def from_str(cls, value: str) -> "ProviderCapability":
        """Parse string to capability enum with normalization."""
        norm = value.strip().lower().replace(" ", "_").replace("-", "_")
        for item in cls:
            if item.value == norm or item.name.lower() == norm:
                return item
        raise ValueError(f"Unknown capability '{value}'. Valid: {', '.join(c.value for c in cls)}")
