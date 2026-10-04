"""Canonical internal models for LYRA messages, requests, and responses."""

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Sequence

from lyra.core.exceptions import ModelValidationError


class Role(str, Enum):
    """Enumeration of recognized conversational roles."""

    SYSTEM = "system"
    USER = "user"
    ASSISTANT = "assistant"
    TOOL = "tool"


@dataclass(frozen=True)
class Message:
    """A single conversational message supporting optional multimodal content parts."""

    role: Role
    content: str
    parts: tuple[Any, ...] = ()
    name: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        # Validate or normalize role
        if isinstance(self.role, str):
            try:
                object.__setattr__(self, "role", Role(self.role.lower()))
            except ValueError as err:
                valid = ", ".join(r.value for r in Role)
                raise ModelValidationError(
                    f"Invalid message role '{self.role}'. Expected one of: {valid}"
                ) from err
        elif not isinstance(self.role, Role):
            raise ModelValidationError(f"Invalid message role type: {type(self.role)}")

        if not isinstance(self.content, str):
            raise ModelValidationError("Message content must be a string.")

        if self.parts and not isinstance(self.parts, tuple):
            object.__setattr__(self, "parts", tuple(self.parts))

    def has_images(self) -> bool:
        """Check if message contains one or more image parts."""
        from lyra.models.multimodal import ImagePart
        return any(isinstance(p, ImagePart) for p in self.parts)

    def has_audio(self) -> bool:
        """Check if message contains one or more audio parts."""
        from lyra.models.multimodal import AudioPart
        return any(isinstance(p, AudioPart) for p in self.parts)

    def has_files(self) -> bool:
        """Check if message contains one or more file parts."""
        from lyra.models.multimodal import FilePart
        return any(isinstance(p, FilePart) for p in self.parts)

    def get_images(self) -> tuple[Any, ...]:
        """Extract all image parts."""
        from lyra.models.multimodal import ImagePart
        return tuple(p for p in self.parts if isinstance(p, ImagePart))

    def get_audio(self) -> tuple[Any, ...]:
        """Extract all audio parts."""
        from lyra.models.multimodal import AudioPart
        return tuple(p for p in self.parts if isinstance(p, AudioPart))

    def get_files(self) -> tuple[Any, ...]:
        """Extract all file parts."""
        from lyra.models.multimodal import FilePart
        return tuple(p for p in self.parts if isinstance(p, FilePart))


@dataclass(frozen=True)
class Usage:
    """Token usage metrics for an AI generation."""

    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0

    def __post_init__(self) -> None:
        if self.prompt_tokens < 0 or self.completion_tokens < 0 or self.total_tokens < 0:
            raise ModelValidationError("Token counts must be non-negative.")
        if self.total_tokens == 0 and (self.prompt_tokens > 0 or self.completion_tokens > 0):
            object.__setattr__(self, "total_tokens", self.prompt_tokens + self.completion_tokens)


@dataclass(frozen=True)
class AIRequest:
    """Provider-agnostic request for AI generation."""

    messages: tuple[Message, ...]
    model: str | None = None
    temperature: float | None = None
    max_tokens: int | None = None
    system_prompt: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def __init__(
        self,
        messages: Sequence[Message],
        model: str | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
        system_prompt: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        if not messages:
            raise ModelValidationError("AIRequest requires at least one Message.")

        for idx, msg in enumerate(messages):
            if not isinstance(msg, Message):
                raise ModelValidationError(
                    f"Item at index {idx} in messages is not a Message instance (got {type(msg)})."
                )

        if temperature is not None:
            if not isinstance(temperature, (int, float)) or not (0.0 <= float(temperature) <= 2.0):
                raise ModelValidationError(
                    f"Temperature must be a float between 0.0 and 2.0 (got {temperature})."
                )
            temperature = float(temperature)

        if max_tokens is not None:
            if not isinstance(max_tokens, int) or max_tokens <= 0:
                raise ModelValidationError(
                    f"max_tokens must be a positive integer (got {max_tokens})."
                )

        object.__setattr__(self, "messages", tuple(messages))
        object.__setattr__(self, "model", model)
        object.__setattr__(self, "temperature", temperature)
        object.__setattr__(self, "max_tokens", max_tokens)
        object.__setattr__(self, "system_prompt", system_prompt)
        object.__setattr__(self, "metadata", metadata or {})

    def has_images(self) -> bool:
        """Check if any message in request contains image content."""
        return any(msg.has_images() for msg in self.messages)

    def has_audio(self) -> bool:
        """Check if any message in request contains audio content."""
        return any(msg.has_audio() for msg in self.messages)

    def has_files(self) -> bool:
        """Check if any message in request contains file content."""
        return any(msg.has_files() for msg in self.messages)

    def requires_multimodal(self) -> bool:
        """Check if request requires multimodal vision/audio/file support."""
        return self.has_images() or self.has_audio() or self.has_files()



@dataclass(frozen=True)
class AIResponse:
    """Provider-agnostic response from AI generation."""

    content: str
    model: str
    role: Role = Role.ASSISTANT
    finish_reason: str | None = None
    usage: Usage | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not isinstance(self.content, str):
            raise ModelValidationError("AIResponse content must be a string.")
        if not self.model or not isinstance(self.model, str):
            raise ModelValidationError("AIResponse requires a valid non-empty model identifier.")

        if isinstance(self.role, str):
            try:
                object.__setattr__(self, "role", Role(self.role.lower()))
            except ValueError as err:
                raise ModelValidationError(f"Invalid AIResponse role: {self.role}") from err
