"""Unit tests for MemoryManager orchestration and policy coordination."""

from datetime import datetime, timedelta, timezone
import pytest

from lyra.core.exceptions import MemoryNotFoundError, MemoryPolicyViolationError
from lyra.memory.manager import MemoryManager
from lyra.memory.policy import MemoryPolicy
from lyra.memory.sqlite_repository import SQLiteMemoryRepository
from lyra.models.memory import MemoryType


@pytest.fixture
def manager(tmp_path):
    db_file = str(tmp_path / "test_manager_memory.db")
    repo = SQLiteMemoryRepository(db_path=db_file)
    policy = MemoryPolicy(min_importance=0.2, min_confidence=0.3)
    mgr = MemoryManager(repository=repo, policy=policy)
    yield mgr
    repo.close()


def test_manager_remember_and_recall(manager):
    record = manager.remember(
        user_id="user-1",
        content="I am a software engineer building distributed systems",
        memory_type=MemoryType.FACT,
        importance=0.8,
    )
    assert record.id is not None
    assert record.content == "I am a software engineer building distributed systems"
    assert record.type == MemoryType.FACT

    recalled = manager.recall(record.id, user_id="user-1")
    assert recalled is not None
    assert recalled.content == record.content

    # Another user cannot recall it
    assert manager.recall(record.id, user_id="user-2") is None


def test_manager_policy_violation_rejection(manager):
    # Sensitive credentials rejection
    with pytest.raises(MemoryPolicyViolationError):
        manager.remember(
            user_id="user-1",
            content="Here is my api_key: sk-1234567890abcdef12345678",
            memory_type=MemoryType.FACT,
        )

    # Trivial content rejection
    with pytest.raises(MemoryPolicyViolationError):
        manager.remember(
            user_id="user-1",
            content="ok",
            memory_type=MemoryType.FACT,
        )


def test_manager_modify(manager):
    rec = manager.remember(
        user_id="user-1",
        content="Target is to run 5km",
        memory_type=MemoryType.GOAL,
    )

    updated = manager.modify(
        memory_id=rec.id,
        user_id="user-1",
        content="Target is to run 10km",
        importance=0.9,
    )
    assert updated.content == "Target is to run 10km"
    assert updated.importance == 0.9

    # Modifying non-existent memory raises MemoryNotFoundError
    with pytest.raises(MemoryNotFoundError):
        manager.modify(
            memory_id="ghost-id",
            user_id="user-1",
            content="Some new content",
        )


def test_manager_forget(manager):
    rec = manager.remember(
        user_id="user-1",
        content="Temporary task to remember",
        memory_type=MemoryType.TASK,
    )
    assert manager.recall(rec.id, user_id="user-1") is not None

    deleted = manager.forget(rec.id, user_id="user-1")
    assert deleted is True
    assert manager.recall(rec.id, user_id="user-1") is None


def test_manager_search_and_list(manager):
    manager.remember(user_id="user-1", content="Loves dark roast espresso", memory_type="preference")
    manager.remember(user_id="user-1", content="Enjoys green tea in afternoon", memory_type="habit")
    manager.remember(user_id="user-2", content="Drinks cappuccino", memory_type="preference")

    results = manager.search(user_id="user-1", query="tea")
    assert len(results) == 1
    assert "green tea" in results[0].content

    prefs = manager.list_memories(user_id="user-1", memory_type="preference")
    assert len(prefs) == 1
    assert "dark roast" in prefs[0].content


def test_manager_get_context_summary(manager):
    assert manager.get_context_summary(user_id="user-1") == ""

    manager.remember(user_id="user-1", content="Prefers Python 3.12+", memory_type="preference")
    manager.remember(user_id="user-1", content="Lives in Berlin", memory_type="fact")

    summary = manager.get_context_summary(user_id="user-1")
    assert "User Long-Term Memory:" in summary
    assert "[preference] Prefers Python 3.12+" in summary
    assert "[fact] Lives in Berlin" in summary
