"""Canonical domain models for LYRA persistent memory."""

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any
import uuid

from lyra.core.exceptions import ModelValidationError


class MemoryType(str, Enum):
    """Explicitly supported memory classification categories."""

    PREFERENCE = "preference"
    FACT = "fact"
    GOAL = "goal"
    HABIT = "habit"
    IMPORTANT_EVENT = "important_event"
    TASK = "task"
    CONVERSATION_SUMMARY = "conversation_summary"

    @classmethod
    def from_str(cls, value: str) -> "MemoryType":
        """Convert string to MemoryType with case-insensitivity."""
        normalized = value.strip().lower().replace(" ", "_")
        for item in cls:
            if item.value == normalized:
                return item
        raise ModelValidationError(
            f"Invalid memory type '{value}'. Allowed types: {', '.join(t.value for t in cls)}"
        )


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


@dataclass(frozen=True)
class MemoryRecord:
    """Canonical model for a persisted memory item."""

    id: str
    user_id: str
    type: MemoryType
    content: str
    source: str = "conversation"
    importance: float = 0.5
    confidence: float = 0.9
    created_at: datetime = field(default_factory=_utc_now)
    updated_at: datetime = field(default_factory=_utc_now)
    expires_at: datetime | None = None

    def __post_init__(self) -> None:
        if not self.id or not isinstance(self.id, str) or not self.id.strip():
            raise ModelValidationError("Memory id must be a non-empty string.")
        if not self.user_id or not isinstance(self.user_id, str) or not self.user_id.strip():
            raise ModelValidationError("Memory user_id must be a non-empty string.")
        if not self.content or not isinstance(self.content, str) or not self.content.strip():
            raise ModelValidationError("Memory content must be a non-empty string.")
        if not isinstance(self.type, MemoryType):
            raise ModelValidationError(f"Invalid memory type: {self.type}")
        if not 0.0 <= self.importance <= 1.0:
            raise ModelValidationError(f"Memory importance must be between 0.0 and 1.0 (got {self.importance}).")
        if not 0.0 <= self.confidence <= 1.0:
            raise ModelValidationError(f"Memory confidence must be between 0.0 and 1.0 (got {self.confidence}).")

    def is_expired(self, current_time: datetime | None = None) -> bool:
        """Check if this memory record has passed its expiration timestamp."""
        if self.expires_at is None:
            return False
        now = current_time or _utc_now()
        # Handle timezone awareness
        exp = self.expires_at if self.expires_at.tzinfo else self.expires_at.replace(tzinfo=timezone.utc)
        curr = now if now.tzinfo else now.replace(tzinfo=timezone.utc)
        return curr >= exp

    def to_dict(self) -> dict[str, Any]:
        """Convert record into serialized dictionary."""
        return {
            "id": self.id,
            "user_id": self.user_id,
            "type": self.type.value,
            "content": self.content,
            "source": self.source,
            "importance": self.importance,
            "confidence": self.confidence,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
            "expires_at": self.expires_at.isoformat() if self.expires_at else None,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "MemoryRecord":
        """Reconstruct record from dictionary representation."""
        created_str = data.get("created_at")
        updated_str = data.get("updated_at")
        expires_str = data.get("expires_at")

        created_at = (
            datetime.fromisoformat(created_str)
            if created_str
            else _utc_now()
        )
        updated_at = (
            datetime.fromisoformat(updated_str)
            if updated_str
            else created_at
        )
        expires_at = (
            datetime.fromisoformat(expires_str)
            if expires_str
            else None
        )

        return cls(
            id=data["id"],
            user_id=data["user_id"],
            type=MemoryType.from_str(data["type"]),
            content=data["content"],
            source=data.get("source", "conversation"),
            importance=float(data.get("importance", 0.5)),
            confidence=float(data.get("confidence", 0.9)),
            created_at=created_at,
            updated_at=updated_at,
            expires_at=expires_at,
        )
