"""Unit tests for SQLiteMemoryRepository persistence and tenant isolation."""

from datetime import datetime, timedelta, timezone
import pytest

from lyra.core.exceptions import MemoryNotFoundError
from lyra.memory.sqlite_repository import SQLiteMemoryRepository
from lyra.models.memory import MemoryRecord, MemoryType


@pytest.fixture
def repo(tmp_path):
    db_file = str(tmp_path / "test_memory.db")
    repository = SQLiteMemoryRepository(db_path=db_file)
    yield repository
    repository.close()


def test_repository_store_and_get(repo):
    rec = MemoryRecord(
        id="mem-1",
        user_id="user-a",
        type=MemoryType.PREFERENCE,
        content="Prefers vim over nano",
        importance=0.8,
    )
    repo.store(rec)

    fetched = repo.get("mem-1", user_id="user-a")
    assert fetched is not None
    assert fetched.id == "mem-1"
    assert fetched.content == "Prefers vim over nano"
    assert fetched.type == MemoryType.PREFERENCE


def test_repository_user_isolation(repo):
    rec_a = MemoryRecord(
        id="mem-a",
        user_id="user-a",
        type=MemoryType.FACT,
        content="User A secret fact",
    )
    rec_b = MemoryRecord(
        id="mem-b",
        user_id="user-b",
        type=MemoryType.FACT,
        content="User B fact",
    )
    repo.store(rec_a)
    repo.store(rec_b)

    # user-b cannot access user-a's memory
    assert repo.get("mem-a", user_id="user-b") is None
    assert repo.get("mem-b", user_id="user-a") is None

    # List queries strictly partition by user_id
    list_a = repo.list_memories(user_id="user-a")
    assert len(list_a) == 1
    assert list_a[0].id == "mem-a"

    list_b = repo.list_memories(user_id="user-b")
    assert len(list_b) == 1
    assert list_b[0].id == "mem-b"

    # Search queries also partition strictly
    search_a = repo.search(user_id="user-a", query="fact")
    assert len(search_a) == 1
    assert search_a[0].id == "mem-a"


def test_repository_update(repo):
    rec = MemoryRecord(
        id="mem-update",
        user_id="user-a",
        type=MemoryType.GOAL,
        content="Run 5km",
    )
    repo.store(rec)

    updated_rec = MemoryRecord(
        id="mem-update",
        user_id="user-a",
        type=MemoryType.GOAL,
        content="Run 10km",
        importance=0.9,
    )
    repo.update(updated_rec)

    fetched = repo.get("mem-update", user_id="user-a")
    assert fetched is not None
    assert fetched.content == "Run 10km"
    assert fetched.importance == 0.9

    # Updating non-existent memory raises MemoryNotFoundError
    ghost_rec = MemoryRecord(
        id="mem-ghost",
        user_id="user-a",
        type=MemoryType.GOAL,
        content="Nonexistent",
    )
    with pytest.raises(MemoryNotFoundError):
        repo.update(ghost_rec)


def test_repository_delete(repo):
    rec = MemoryRecord(
        id="mem-del",
        user_id="user-a",
        type=MemoryType.HABIT,
        content="Drink water after waking up",
    )
    repo.store(rec)

    # Deleting as wrong user returns False
    assert repo.delete("mem-del", user_id="user-b") is False
    assert repo.get("mem-del", user_id="user-a") is not None

    # Deleting as owner returns True
    assert repo.delete("mem-del", user_id="user-a") is True
    assert repo.get("mem-del", user_id="user-a") is None


def test_repository_expiration_filtering(repo):
    past = datetime.now(timezone.utc) - timedelta(hours=2)
    rec_expired = MemoryRecord(
        id="mem-expired",
        user_id="user-a",
        type=MemoryType.TASK,
        content="Call dentist",
        expires_at=past,
    )
    rec_active = MemoryRecord(
        id="mem-active",
        user_id="user-a",
        type=MemoryType.TASK,
        content="Call doctor",
    )
    repo.store(rec_expired)
    repo.store(rec_active)

    # Excluded by default
    active_mems = repo.list_memories(user_id="user-a", include_expired=False)
    assert len(active_mems) == 1
    assert active_mems[0].id == "mem-active"

    # Included when requested
    all_mems = repo.list_memories(user_id="user-a", include_expired=True)
    assert len(all_mems) == 2


def test_repository_purge_user(repo):
    repo.store(MemoryRecord(id="p1", user_id="target-user", type=MemoryType.FACT, content="Fact 1"))
    repo.store(MemoryRecord(id="p2", user_id="target-user", type=MemoryType.FACT, content="Fact 2"))
    repo.store(MemoryRecord(id="p3", user_id="other-user", type=MemoryType.FACT, content="Fact 3"))

    purged = repo.purge_user("target-user")
    assert purged == 2
    assert len(repo.list_memories("target-user")) == 0
    assert len(repo.list_memories("other-user")) == 1
