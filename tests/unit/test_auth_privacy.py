"""Unit tests for AuthManager and Data Privacy (export, purge, user memory isolation)."""

import pytest

from lyra.auth.local import LocalAuthProvider
from lyra.auth.manager import AuthManager
from lyra.core.exceptions import AuthenticationFailedError, UserNotFoundError
from lyra.memory.manager import MemoryManager
from lyra.memory.policy import MemoryPolicy
from lyra.memory.sqlite_repository import SQLiteMemoryRepository
from lyra.models.memory import MemoryType


@pytest.fixture
def auth_and_memory_managers(tmp_path):
    """Provide initialized AuthManager and MemoryManager with temporary SQLite databases."""
    auth_db = str(tmp_path / "test_privacy_auth.db")
    memory_db = str(tmp_path / "test_privacy_memory.db")

    auth_provider = LocalAuthProvider(db_path=auth_db)
    memory_repo = SQLiteMemoryRepository(db_path=memory_db)
    memory_manager = MemoryManager(repository=memory_repo, policy=MemoryPolicy())

    auth_manager = AuthManager(provider=auth_provider, memory_manager=memory_manager)
    return auth_manager, memory_manager


def test_auth_manager_login_and_logout(auth_and_memory_managers):
    """Verify AuthManager login and token logout."""
    auth_mgr, _ = auth_and_memory_managers

    # Register
    user = auth_mgr.register(username="rory", password="RoryPassword123")
    assert user.username == "rory"

    # Login
    logged_user, token = auth_mgr.login(username="rory", password="RoryPassword123")
    assert logged_user.id == user.id
    assert auth_mgr.validate_session(token) is not None

    # Failed login
    with pytest.raises(AuthenticationFailedError):
        auth_mgr.login(username="rory", password="WrongPassword")

    # Logout
    revoked = auth_mgr.logout(token)
    assert revoked is True
    assert auth_mgr.validate_session(token) is None


def test_export_user_data_and_isolation(auth_and_memory_managers):
    """Verify user data export includes user profile and memories while maintaining strict user isolation."""
    auth_mgr, memory_mgr = auth_and_memory_managers

    user1 = auth_mgr.register(username="user_one", password="PasswordOne123")
    user2 = auth_mgr.register(username="user_two", password="PasswordTwo123")

    # Store memories for User 1
    memory_mgr.remember(
        user_id=user1.id,
        content="Loves Earl Grey tea",
        memory_type=MemoryType.PREFERENCE,
    )
    memory_mgr.remember(
        user_id=user1.id,
        content="Lives in Edinburgh",
        memory_type=MemoryType.FACT,
    )

    # Store memories for User 2
    memory_mgr.remember(
        user_id=user2.id,
        content="Prefers dark chocolate",
        memory_type=MemoryType.PREFERENCE,
    )

    # Export User 1 data
    export1 = auth_mgr.export_user_data(user1.id)
    assert export1["user"]["username"] == "user_one"
    assert len(export1["memories"]) == 2
    contents1 = [m["content"] for m in export1["memories"]]
    assert "Loves Earl Grey tea" in contents1
    assert "Lives in Edinburgh" in contents1
    assert "Prefers dark chocolate" not in contents1  # User 2 data must not leak!

    # Export User 2 data
    export2 = auth_mgr.export_user_data(user2.id)
    assert export2["user"]["username"] == "user_two"
    assert len(export2["memories"]) == 1
    assert export2["memories"][0]["content"] == "Prefers dark chocolate"


def test_delete_user_data_purges_profile_and_memories(auth_and_memory_managers):
    """Verify delete_user_data permanently purges identity, tokens, and all memories."""
    auth_mgr, memory_mgr = auth_and_memory_managers

    user_a = auth_mgr.register(username="to_delete", password="Password123")
    user_b = auth_mgr.register(username="survivor", password="Password123")

    memory_mgr.remember(
        user_id=user_a.id,
        content="Secret plan to erase",
        memory_type=MemoryType.GOAL,
    )
    memory_mgr.remember(
        user_id=user_b.id,
        content="Persistent knowledge for user B",
        memory_type=MemoryType.FACT,
    )

    # Delete User A
    deleted = auth_mgr.delete_user_data(user_a.id)
    assert deleted is True

    # User A account must no longer exist
    assert auth_mgr.get_user(user_a.id) is None

    # User A memories must be purged
    assert len(memory_mgr.list_memories(user_a.id)) == 0

    # User B account and memories must remain completely intact
    assert auth_mgr.get_user(user_b.id) is not None
    memories_b = memory_mgr.list_memories(user_b.id)
    assert len(memories_b) == 1
    assert memories_b[0].content == "Persistent knowledge for user B"

    # Deleting non-existent user raises UserNotFoundError
    with pytest.raises(UserNotFoundError):
        auth_mgr.delete_user_data("non_existent_id")
