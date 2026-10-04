"""Abstract base interface for memory storage repositories."""

from abc import ABC, abstractmethod

from lyra.models.memory import MemoryRecord, MemoryType


class MemoryRepository(ABC):
    """Abstract storage repository for persistent memory records.

    Provides user-isolated persistence enabling database swapping (SQLite, PostgreSQL, etc.)
    without modifying core memory business logic.
    """

    @abstractmethod
    def store(self, record: MemoryRecord) -> None:
        """Store a memory record or overwrite if identical ID exists for this user."""

    @abstractmethod
    def get(self, memory_id: str, user_id: str) -> MemoryRecord | None:
        """Retrieve a specific memory record enforcing user isolation."""

    @abstractmethod
    def update(self, record: MemoryRecord) -> None:
        """Update an existing memory record enforcing user isolation."""

    @abstractmethod
    def delete(self, memory_id: str, user_id: str) -> bool:
        """Delete a memory record by ID for a specific user. Returns True if found and removed."""

    @abstractmethod
    def list_memories(
        self,
        user_id: str,
        memory_type: MemoryType | None = None,
        limit: int = 50,
        include_expired: bool = False,
    ) -> list[MemoryRecord]:
        """List memories for a user, optionally filtered by category."""

    @abstractmethod
    def search(
        self,
        user_id: str,
        query: str,
        memory_type: MemoryType | None = None,
        limit: int = 10,
        include_expired: bool = False,
    ) -> list[MemoryRecord]:
        """Search memories containing query keywords for a specific user."""

    @abstractmethod
    def purge_user(self, user_id: str) -> int:
        """Delete all memories belonging to a specific user (returns count of purged records)."""
