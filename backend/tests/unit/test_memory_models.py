"""Unit tests for LYRA memory domain models."""

from datetime import datetime, timedelta, timezone
import pytest

from lyra.core.exceptions import ModelValidationError
from lyra.models.memory import MemoryRecord, MemoryType


def test_memory_type_parsing():
    assert MemoryType.from_str("preference") == MemoryType.PREFERENCE
    assert MemoryType.from_str("Preference") == MemoryType.PREFERENCE
    assert MemoryType.from_str("FACT") == MemoryType.FACT
    assert MemoryType.from_str("goal") == MemoryType.GOAL
    assert MemoryType.from_str("habit") == MemoryType.HABIT
    assert MemoryType.from_str("important_event") == MemoryType.IMPORTANT_EVENT
    assert MemoryType.from_str("important event") == MemoryType.IMPORTANT_EVENT
    assert MemoryType.from_str("task") == MemoryType.TASK
    assert MemoryType.from_str("conversation_summary") == MemoryType.CONVERSATION_SUMMARY
    assert MemoryType.from_str("conversation summary") == MemoryType.CONVERSATION_SUMMARY

    with pytest.raises(ModelValidationError):
        MemoryType.from_str("invalid_category")


def test_memory_record_creation_and_validation():
    rec = MemoryRecord(
        id="mem-123",
        user_id="user-1",
        type=MemoryType.PREFERENCE,
        content="Prefers dark theme",
        importance=0.8,
        confidence=0.95,
    )
    assert rec.id == "mem-123"
    assert rec.user_id == "user-1"
    assert rec.type == MemoryType.PREFERENCE
    assert rec.content == "Prefers dark theme"
    assert rec.importance == 0.8
    assert rec.confidence == 0.95
    assert not rec.is_expired()


def test_memory_record_invalid_parameters():
    with pytest.raises(ModelValidationError):
        MemoryRecord(id="", user_id="user-1", type=MemoryType.FACT, content="Hello")

    with pytest.raises(ModelValidationError):
        MemoryRecord(id="1", user_id="", type=MemoryType.FACT, content="Hello")

    with pytest.raises(ModelValidationError):
        MemoryRecord(id="1", user_id="user-1", type=MemoryType.FACT, content="")

    with pytest.raises(ModelValidationError):
        MemoryRecord(id="1", user_id="user-1", type=MemoryType.FACT, content="Val", importance=1.5)

    with pytest.raises(ModelValidationError):
        MemoryRecord(id="1", user_id="user-1", type=MemoryType.FACT, content="Val", confidence=-0.1)


def test_memory_record_expiration():
    past = datetime.now(timezone.utc) - timedelta(hours=1)
    future = datetime.now(timezone.utc) + timedelta(hours=1)

    expired_rec = MemoryRecord(
        id="mem-exp",
        user_id="user-1",
        type=MemoryType.TASK,
        content="Buy groceries",
        expires_at=past,
    )
    assert expired_rec.is_expired()

    active_rec = MemoryRecord(
        id="mem-act",
        user_id="user-1",
        type=MemoryType.TASK,
        content="Buy groceries",
        expires_at=future,
    )
    assert not active_rec.is_expired()


def test_memory_record_serialization_roundtrip():
    original = MemoryRecord(
        id="mem-rt",
        user_id="u-42",
        type=MemoryType.GOAL,
        content="Finish marathon in October",
        source="cli_command",
        importance=0.9,
        confidence=1.0,
    )
    data = original.to_dict()
    assert data["id"] == "mem-rt"
    assert data["user_id"] == "u-42"
    assert data["type"] == "goal"

    restored = MemoryRecord.from_dict(data)
    assert restored.id == original.id
    assert restored.user_id == original.user_id
    assert restored.type == original.type
    assert restored.content == original.content
    assert restored.importance == original.importance
