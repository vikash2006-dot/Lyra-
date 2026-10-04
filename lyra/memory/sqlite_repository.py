"""SQLite implementation of the MemoryRepository interface."""

from datetime import datetime, timezone
import sqlite3
import threading
from typing import Any

from lyra.core.exceptions import MemoryNotFoundError, MemoryStorageError
from lyra.memory.repository import MemoryRepository
from lyra.models.memory import MemoryRecord, MemoryType


class SQLiteMemoryRepository(MemoryRepository):
    """SQLite-backed persistent memory repository enforcing strict user isolation."""

    def __init__(self, db_path: str = "lyra_memory.db") -> None:
        self.db_path = db_path
        self._lock = threading.Lock()
        self._conn: sqlite3.Connection | None = None
        self._init_db()

    def _get_connection(self) -> sqlite3.Connection:
        if self._conn is None:
            try:
                self._conn = sqlite3.connect(
                    self.db_path,
                    check_same_thread=False,
                    autocommit=False,
                )
                self._conn.row_factory = sqlite3.Row
            except sqlite3.Error as e:
                raise MemoryStorageError(f"Failed to connect to SQLite memory database: {e}") from e
        return self._conn

    def _init_db(self) -> None:
        """Initialize database schema and indices."""
        with self._lock:
            conn = self._get_connection()
            try:
                with conn:
                    conn.execute("""
                        CREATE TABLE IF NOT EXISTS memories (
                            id TEXT PRIMARY KEY,
                            user_id TEXT NOT NULL,
                            type TEXT NOT NULL,
                            content TEXT NOT NULL,
                            source TEXT NOT NULL,
                            importance REAL NOT NULL,
                            confidence REAL NOT NULL,
                            created_at TEXT NOT NULL,
                            updated_at TEXT NOT NULL,
                            expires_at TEXT
                        )
                    """)
                    conn.execute("""
                        CREATE INDEX IF NOT EXISTS idx_memories_user_type
                        ON memories(user_id, type)
                    """)
                    conn.execute("""
                        CREATE INDEX IF NOT EXISTS idx_memories_user_updated
                        ON memories(user_id, updated_at DESC)
                    """)
            except sqlite3.Error as e:
                raise MemoryStorageError(f"Failed to initialize memory schema: {e}") from e

    def _row_to_record(self, row: sqlite3.Row) -> MemoryRecord:
        """Convert a SQLite row to a MemoryRecord domain model."""
        return MemoryRecord.from_dict({
            "id": row["id"],
            "user_id": row["user_id"],
            "type": row["type"],
            "content": row["content"],
            "source": row["source"],
            "importance": row["importance"],
            "confidence": row["confidence"],
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
            "expires_at": row["expires_at"],
        })

    def store(self, record: MemoryRecord) -> None:
        """Store or replace a memory record."""
        with self._lock:
            conn = self._get_connection()
            try:
                with conn:
                    conn.execute(
                        """
                        INSERT INTO memories (
                            id, user_id, type, content, source,
                            importance, confidence, created_at, updated_at, expires_at
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        ON CONFLICT(id) DO UPDATE SET
                            user_id = excluded.user_id,
                            type = excluded.type,
                            content = excluded.content,
                            source = excluded.source,
                            importance = excluded.importance,
                            confidence = excluded.confidence,
                            created_at = excluded.created_at,
                            updated_at = excluded.updated_at,
                            expires_at = excluded.expires_at
                        """,
                        (
                            record.id,
                            record.user_id,
                            record.type.value,
                            record.content,
                            record.source,
                            record.importance,
                            record.confidence,
                            record.created_at.isoformat(),
                            record.updated_at.isoformat(),
                            record.expires_at.isoformat() if record.expires_at else None,
                        ),
                    )
            except sqlite3.Error as e:
                raise MemoryStorageError(f"Failed to store memory record {record.id}: {e}") from e

    def get(self, memory_id: str, user_id: str) -> MemoryRecord | None:
        """Retrieve a specific memory record enforcing user isolation."""
        with self._lock:
            conn = self._get_connection()
            try:
                cursor = conn.execute(
                    "SELECT * FROM memories WHERE id = ? AND user_id = ?",
                    (memory_id, user_id),
                )
                row = cursor.fetchone()
                if not row:
                    return None
                return self._row_to_record(row)
            except sqlite3.Error as e:
                raise MemoryStorageError(f"Failed to retrieve memory record {memory_id}: {e}") from e

    def update(self, record: MemoryRecord) -> None:
        """Update an existing memory record enforcing user isolation."""
        with self._lock:
            conn = self._get_connection()
            try:
                with conn:
                    cursor = conn.execute(
                        """
                        UPDATE memories
                        SET type = ?, content = ?, source = ?, importance = ?,
                            confidence = ?, updated_at = ?, expires_at = ?
                        WHERE id = ? AND user_id = ?
                        """,
                        (
                            record.type.value,
                            record.content,
                            record.source,
                            record.importance,
                            record.confidence,
                            record.updated_at.isoformat(),
                            record.expires_at.isoformat() if record.expires_at else None,
                            record.id,
                            record.user_id,
                        ),
                    )
                    if cursor.rowcount == 0:
                        raise MemoryNotFoundError(
                            f"Memory with id '{record.id}' not found for user '{record.user_id}'."
                        )
            except MemoryNotFoundError:
                raise
            except sqlite3.Error as e:
                raise MemoryStorageError(f"Failed to update memory record {record.id}: {e}") from e

    def delete(self, memory_id: str, user_id: str) -> bool:
        """Delete a memory record by ID for a specific user."""
        with self._lock:
            conn = self._get_connection()
            try:
                with conn:
                    cursor = conn.execute(
                        "DELETE FROM memories WHERE id = ? AND user_id = ?",
                        (memory_id, user_id),
                    )
                    return cursor.rowcount > 0
            except sqlite3.Error as e:
                raise MemoryStorageError(f"Failed to delete memory record {memory_id}: {e}") from e

    def list_memories(
        self,
        user_id: str,
        memory_type: MemoryType | None = None,
        limit: int = 50,
        include_expired: bool = False,
    ) -> list[MemoryRecord]:
        """List memories for a user, optionally filtered by category."""
        with self._lock:
            conn = self._get_connection()
            try:
                query = "SELECT * FROM memories WHERE user_id = ?"
                params: list[Any] = [user_id]

                if memory_type is not None:
                    query += " AND type = ?"
                    params.append(memory_type.value)

                query += " ORDER BY updated_at DESC LIMIT ?"
                params.append(limit)

                cursor = conn.execute(query, params)
                rows = cursor.fetchall()
                records = [self._row_to_record(row) for row in rows]

                if not include_expired:
                    now = datetime.now(timezone.utc)
                    records = [r for r in records if not r.is_expired(now)]

                return records
            except sqlite3.Error as e:
                raise MemoryStorageError(f"Failed to list memories for user {user_id}: {e}") from e

    def search(
        self,
        user_id: str,
        query: str,
        memory_type: MemoryType | None = None,
        limit: int = 10,
        include_expired: bool = False,
    ) -> list[MemoryRecord]:
        """Search memories containing query keywords for a specific user."""
        with self._lock:
            conn = self._get_connection()
            try:
                sql = "SELECT * FROM memories WHERE user_id = ? AND content LIKE ?"
                params: list[Any] = [user_id, f"%{query}%"]

                if memory_type is not None:
                    sql += " AND type = ?"
                    params.append(memory_type.value)

                sql += " ORDER BY updated_at DESC LIMIT ?"
                params.append(limit)

                cursor = conn.execute(sql, params)
                rows = cursor.fetchall()
                records = [self._row_to_record(row) for row in rows]

                if not include_expired:
                    now = datetime.now(timezone.utc)
                    records = [r for r in records if not r.is_expired(now)]

                return records
            except sqlite3.Error as e:
                raise MemoryStorageError(f"Failed to search memories for user {user_id}: {e}") from e

    def purge_user(self, user_id: str) -> int:
        """Delete all memories belonging to a specific user."""
        with self._lock:
            conn = self._get_connection()
            try:
                with conn:
                    cursor = conn.execute("DELETE FROM memories WHERE user_id = ?", (user_id,))
                    return cursor.rowcount
            except sqlite3.Error as e:
                raise MemoryStorageError(f"Failed to purge memories for user {user_id}: {e}") from e

    def close(self) -> None:
        """Close SQLite database connection."""
        with self._lock:
            if self._conn is not None:
                try:
                    self._conn.close()
                except sqlite3.Error:
                    pass
                self._conn = None
