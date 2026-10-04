"""High-level MemoryManager orchestrating memory persistence, retrieval, and policies."""

from datetime import datetime, timezone
import uuid

from lyra.core.exceptions import MemoryNotFoundError, MemoryPolicyViolationError
from lyra.memory.policy import MemoryPolicy
from lyra.memory.repository import MemoryRepository
from lyra.models.memory import MemoryRecord, MemoryType
from lyra.observability.logging import get_logger

logger = get_logger("memory.manager")


class MemoryManager:
    """Manages user-isolated persistent memory with policy enforcement and search capabilities."""

    def __init__(
        self,
        repository: MemoryRepository,
        policy: MemoryPolicy | None = None,
    ) -> None:
        self.repository = repository
        self.policy = policy or MemoryPolicy()

    def _parse_memory_type(self, memory_type: MemoryType | str) -> MemoryType:
        if isinstance(memory_type, MemoryType):
            return memory_type
        return MemoryType.from_str(memory_type)

    def remember(
        self,
        user_id: str,
        content: str,
        memory_type: MemoryType | str,
        source: str = "conversation",
        importance: float = 0.5,
        confidence: float = 0.9,
        expires_at: datetime | None = None,
        memory_id: str | None = None,
    ) -> MemoryRecord:
        """Evaluate, create, and store a permitted memory record."""
        target_type = self._parse_memory_type(memory_type)

        # Policy check
        allowed, reason = self.policy.evaluate_candidate(
            user_id=user_id,
            content=content,
            memory_type=target_type,
            importance=importance,
            confidence=confidence,
        )
        if not allowed:
            logger.warning(
                "Memory policy rejected candidate for user '%s': %s",
                user_id,
                reason,
            )
            raise MemoryPolicyViolationError(
                f"Memory rejected by policy: {reason or 'Candidate does not satisfy retention criteria.'}"
            )

        now = datetime.now(timezone.utc)
        record = MemoryRecord(
            id=memory_id or str(uuid.uuid4()),
            user_id=user_id.strip(),
            type=target_type,
            content=content.strip(),
            source=source.strip(),
            importance=importance,
            confidence=confidence,
            created_at=now,
            updated_at=now,
            expires_at=expires_at,
        )

        self.repository.store(record)
        logger.info(
            "Stored memory [%s] for user '%s' (%s)",
            record.id,
            user_id,
            record.type.value,
        )
        return record

    def recall(self, memory_id: str, user_id: str) -> MemoryRecord | None:
        """Retrieve a specific memory record by ID, checking expiration."""
        record = self.repository.get(memory_id=memory_id, user_id=user_id)
        if record is None:
            return None
        if record.is_expired():
            return None
        return record

    def modify(
        self,
        memory_id: str,
        user_id: str,
        content: str | None = None,
        memory_type: MemoryType | str | None = None,
        importance: float | None = None,
        confidence: float | None = None,
        expires_at: datetime | None = None,
    ) -> MemoryRecord:
        """Modify an existing memory record, re-evaluating policy if content or type changes."""
        existing = self.repository.get(memory_id=memory_id, user_id=user_id)
        if existing is None or existing.is_expired():
            raise MemoryNotFoundError(
                f"Memory record '{memory_id}' not found for user '{user_id}'."
            )

        new_content = content.strip() if content is not None else existing.content
        new_type = self._parse_memory_type(memory_type) if memory_type is not None else existing.type
        new_importance = importance if importance is not None else existing.importance
        new_confidence = confidence if confidence is not None else existing.confidence
        new_expires_at = expires_at if expires_at is not None else existing.expires_at

        # Re-evaluate policy if changed
        if content is not None or memory_type is not None:
            allowed, reason = self.policy.evaluate_candidate(
                user_id=user_id,
                content=new_content,
                memory_type=new_type,
                importance=new_importance,
                confidence=new_confidence,
            )
            if not allowed:
                raise MemoryPolicyViolationError(
                    f"Memory modification rejected by policy: {reason}"
                )

        updated_record = MemoryRecord(
            id=existing.id,
            user_id=existing.user_id,
            type=new_type,
            content=new_content,
            source=existing.source,
            importance=new_importance,
            confidence=new_confidence,
            created_at=existing.created_at,
            updated_at=datetime.now(timezone.utc),
            expires_at=new_expires_at,
        )

        self.repository.update(updated_record)
        logger.info("Updated memory [%s] for user '%s'", memory_id, user_id)
        return updated_record

    def forget(self, memory_id: str, user_id: str) -> bool:
        """Delete a memory record for the user. Returns True if deleted."""
        deleted = self.repository.delete(memory_id=memory_id, user_id=user_id)
        if deleted:
            logger.info("Deleted memory [%s] for user '%s'", memory_id, user_id)
        return deleted

    def search(
        self,
        user_id: str,
        query: str,
        memory_type: MemoryType | str | None = None,
        limit: int = 10,
    ) -> list[MemoryRecord]:
        """Search memories containing query keywords."""
        target_type = self._parse_memory_type(memory_type) if memory_type else None
        return self.repository.search(
            user_id=user_id,
            query=query,
            memory_type=target_type,
            limit=limit,
            include_expired=False,
        )

    def list_memories(
        self,
        user_id: str,
        memory_type: MemoryType | str | None = None,
        limit: int = 50,
    ) -> list[MemoryRecord]:
        """List active memories for the user, optionally filtered by category."""
        target_type = self._parse_memory_type(memory_type) if memory_type else None
        return self.repository.list_memories(
            user_id=user_id,
            memory_type=target_type,
            limit=limit,
            include_expired=False,
        )

    def purge_all(self, user_id: str) -> int:
        """Purge all memories belonging to a specific user."""
        count = self.repository.purge_user(user_id=user_id)
        logger.info("Purged %d memories for user '%s'", count, user_id)
        return count

    def get_context_summary(self, user_id: str, max_items: int = 15) -> str:
        """Generate a concise memory summary block for injection into AI context."""
        memories = self.repository.list_memories(
            user_id=user_id,
            limit=max_items,
            include_expired=False,
        )
        if not memories:
            return ""

        lines = ["User Long-Term Memory:"]
        for m in memories:
            lines.append(f"- [{m.type.value}] {m.content}")
        return "\n".join(lines)
