"""SQLite persistence for API-level records: chat sessions, messages, tasks, documents.

LYRA's domain data (memory, learning, auth, automation) stays in its existing
databases; this store only adds what the web interface needs to survive restarts.
"""

from __future__ import annotations

from contextlib import contextmanager
import json
from pathlib import Path
import sqlite3
import threading
import time
from typing import Any, Iterator

SCHEMA = """
CREATE TABLE IF NOT EXISTS sessions (
    id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL,
    title TEXT NOT NULL DEFAULT 'New chat',
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
    role TEXT NOT NULL,
    content TEXT NOT NULL,
    metadata TEXT NOT NULL DEFAULT '{}',
    created_at REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_messages_session ON messages(session_id, id);
CREATE TABLE IF NOT EXISTS tasks (
    id TEXT PRIMARY KEY,
    session_id TEXT,
    command TEXT NOT NULL,
    data TEXT NOT NULL,
    status TEXT NOT NULL,
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_tasks_created ON tasks(created_at DESC);
CREATE TABLE IF NOT EXISTS documents (
    id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL,
    filename TEXT NOT NULL,
    stored_path TEXT NOT NULL,
    mime_type TEXT NOT NULL,
    size_bytes INTEGER NOT NULL,
    analysis TEXT,
    created_at REAL NOT NULL
);
"""


class APIStore:
    def __init__(self, db_path: str | Path) -> None:
        self.db_path = str(db_path)
        Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        with self._conn() as conn:
            conn.executescript(SCHEMA)

    @contextmanager
    def _conn(self) -> Iterator[sqlite3.Connection]:
        with self._lock:
            conn = sqlite3.connect(self.db_path)
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA foreign_keys = ON")
            try:
                yield conn
                conn.commit()
            finally:
                conn.close()

    def ping(self) -> bool:
        try:
            with self._conn() as conn:
                conn.execute("SELECT 1")
            return True
        except sqlite3.Error:
            return False

    # Sessions -----------------------------------------------------------------
    def create_session(self, session_id: str, user_id: str, title: str) -> dict[str, Any]:
        now = time.time()
        with self._conn() as conn:
            conn.execute(
                "INSERT INTO sessions (id, user_id, title, created_at, updated_at) VALUES (?, ?, ?, ?, ?)",
                (session_id, user_id, title, now, now),
            )
        return self.get_session(session_id)  # type: ignore[return-value]

    def get_session(self, session_id: str) -> dict[str, Any] | None:
        with self._conn() as conn:
            row = conn.execute(
                "SELECT s.*, (SELECT COUNT(*) FROM messages m WHERE m.session_id = s.id) AS message_count,"
                " (SELECT content FROM messages m WHERE m.session_id = s.id ORDER BY id DESC LIMIT 1) AS last_message"
                " FROM sessions s WHERE s.id = ?",
                (session_id,),
            ).fetchone()
        return dict(row) if row else None

    def list_sessions(self, user_id: str, limit: int = 100) -> list[dict[str, Any]]:
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT s.*, (SELECT COUNT(*) FROM messages m WHERE m.session_id = s.id) AS message_count,"
                " (SELECT content FROM messages m WHERE m.session_id = s.id ORDER BY id DESC LIMIT 1) AS last_message"
                " FROM sessions s WHERE s.user_id = ? ORDER BY s.updated_at DESC LIMIT ?",
                (user_id, limit),
            ).fetchall()
        return [dict(r) for r in rows]

    def rename_session(self, session_id: str, title: str) -> None:
        with self._conn() as conn:
            conn.execute("UPDATE sessions SET title = ? WHERE id = ?", (title, session_id))

    def touch_session(self, session_id: str) -> None:
        with self._conn() as conn:
            conn.execute("UPDATE sessions SET updated_at = ? WHERE id = ?", (time.time(), session_id))

    def delete_session(self, session_id: str) -> bool:
        with self._conn() as conn:
            conn.execute("DELETE FROM messages WHERE session_id = ?", (session_id,))
            cur = conn.execute("DELETE FROM sessions WHERE id = ?", (session_id,))
        return cur.rowcount > 0

    # Messages -----------------------------------------------------------------
    def add_messages(self, session_id: str, messages: list[tuple[str, str, dict[str, Any]]]) -> None:
        if not messages:
            return
        now = time.time()
        with self._conn() as conn:
            conn.executemany(
                "INSERT INTO messages (session_id, role, content, metadata, created_at) VALUES (?, ?, ?, ?, ?)",
                [(session_id, role, content, json.dumps(meta, default=str), now) for role, content, meta in messages],
            )
            conn.execute("UPDATE sessions SET updated_at = ? WHERE id = ?", (now, session_id))

    def list_messages(self, session_id: str, limit: int | None = None) -> list[dict[str, Any]]:
        with self._conn() as conn:
            if limit:
                rows = conn.execute(
                    "SELECT * FROM (SELECT * FROM messages WHERE session_id = ? ORDER BY id DESC LIMIT ?) ORDER BY id",
                    (session_id, limit),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM messages WHERE session_id = ? ORDER BY id", (session_id,)
                ).fetchall()
        out = []
        for r in rows:
            d = dict(r)
            d["metadata"] = json.loads(d.get("metadata") or "{}")
            out.append(d)
        return out

    # Tasks --------------------------------------------------------------------
    def save_task(self, task: dict[str, Any]) -> None:
        with self._conn() as conn:
            conn.execute(
                "INSERT INTO tasks (id, session_id, command, data, status, created_at, updated_at)"
                " VALUES (?, ?, ?, ?, ?, ?, ?)"
                " ON CONFLICT(id) DO UPDATE SET data = excluded.data, status = excluded.status,"
                " updated_at = excluded.updated_at",
                (
                    task["id"],
                    task.get("session_id"),
                    task["command"],
                    json.dumps(task, default=str),
                    task["status"],
                    task["created_ts"],
                    time.time(),
                ),
            )

    def get_task(self, task_id: str) -> dict[str, Any] | None:
        with self._conn() as conn:
            row = conn.execute("SELECT data FROM tasks WHERE id = ?", (task_id,)).fetchone()
        return json.loads(row["data"]) if row else None

    def list_tasks(self, status: str | None = None, limit: int = 50) -> list[dict[str, Any]]:
        with self._conn() as conn:
            if status:
                rows = conn.execute(
                    "SELECT data FROM tasks WHERE status = ? ORDER BY created_at DESC LIMIT ?", (status, limit)
                ).fetchall()
            else:
                rows = conn.execute("SELECT data FROM tasks ORDER BY created_at DESC LIMIT ?", (limit,)).fetchall()
        return [json.loads(r["data"]) for r in rows]

    def mark_interrupted_tasks(self) -> int:
        """Tasks left running by a previous process can never finish; mark them failed."""
        active = ("pending", "planning", "running", "verifying")
        changed = 0
        for task in self.list_tasks(limit=500):
            if task.get("status") in active:
                task["status"] = "failed"
                task["error"] = "Interrupted: the backend restarted before this task finished."
                self.save_task(task)
                changed += 1
        return changed

    # Documents ----------------------------------------------------------------
    def add_document(self, doc: dict[str, Any]) -> None:
        with self._conn() as conn:
            conn.execute(
                "INSERT INTO documents (id, user_id, filename, stored_path, mime_type, size_bytes, analysis, created_at)"
                " VALUES (?, ?, ?, ?, ?, ?, NULL, ?)",
                (doc["id"], doc["user_id"], doc["filename"], doc["stored_path"], doc["mime_type"],
                 doc["size_bytes"], doc["created_at"]),
            )

    def get_document(self, doc_id: str) -> dict[str, Any] | None:
        with self._conn() as conn:
            row = conn.execute("SELECT * FROM documents WHERE id = ?", (doc_id,)).fetchone()
        if not row:
            return None
        d = dict(row)
        d["analysis"] = json.loads(d["analysis"]) if d.get("analysis") else None
        return d

    def list_documents(self, user_id: str) -> list[dict[str, Any]]:
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT * FROM documents WHERE user_id = ? ORDER BY created_at DESC", (user_id,)
            ).fetchall()
        out = []
        for r in rows:
            d = dict(r)
            d["analysis"] = json.loads(d["analysis"]) if d.get("analysis") else None
            out.append(d)
        return out

    def set_document_analysis(self, doc_id: str, analysis: dict[str, Any]) -> None:
        with self._conn() as conn:
            conn.execute(
                "UPDATE documents SET analysis = ? WHERE id = ?", (json.dumps(analysis, default=str), doc_id)
            )

    def delete_document(self, doc_id: str) -> bool:
        with self._conn() as conn:
            cur = conn.execute("DELETE FROM documents WHERE id = ?", (doc_id,))
        return cur.rowcount > 0

    def counts(self) -> dict[str, int]:
        with self._conn() as conn:
            return {
                t: conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
                for t in ("sessions", "messages", "tasks", "documents")
            }
