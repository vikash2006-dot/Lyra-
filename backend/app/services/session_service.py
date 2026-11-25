"""Conversation sessions: LYRA ``Session`` objects backed by persistent storage.

Live ``Session`` instances (used by the orchestrator for context) are cached in memory
and rebuilt from the database on demand, so conversations survive backend restarts.
"""

from __future__ import annotations

import asyncio
from typing import Any
import uuid

from lyra.companion.session import Session
from lyra.models.messages import Message, Role

from app.core.errors import APIError
from app.services.serialization import to_jsonable
from app.services.store import APIStore

DEFAULT_TITLE = "New chat"
HISTORY_LOAD_LIMIT = 200


def _safe_metadata(meta: dict[str, Any]) -> dict[str, Any]:
    clean = to_jsonable(meta) or {}
    # Never persist large tool payloads in chat history metadata.
    return {k: v for k, v in clean.items() if k not in ("task_results", "tool_result")}


class SessionService:
    def __init__(self, store: APIStore, user_id: str) -> None:
        self.store = store
        self.user_id = user_id
        self._live: dict[str, Session] = {}
        self._persisted_count: dict[str, int] = {}
        self._locks: dict[str, asyncio.Lock] = {}

    # CRUD -----------------------------------------------------------------------
    def create(self, title: str | None = None) -> dict[str, Any]:
        session_id = str(uuid.uuid4())
        record = self.store.create_session(session_id, self.user_id, (title or DEFAULT_TITLE).strip()[:120])
        self._live[session_id] = Session(session_id=session_id, user_id=self.user_id)
        self._persisted_count[session_id] = 0
        return record

    def get_record(self, session_id: str) -> dict[str, Any]:
        record = self.store.get_session(session_id)
        if not record or record["user_id"] != self.user_id:
            raise APIError("SESSION_NOT_FOUND", "Conversation not found.", 404)
        return record

    def list(self) -> list[dict[str, Any]]:
        return self.store.list_sessions(self.user_id)

    def rename(self, session_id: str, title: str) -> dict[str, Any]:
        self.get_record(session_id)
        self.store.rename_session(session_id, title.strip()[:120] or DEFAULT_TITLE)
        return self.get_record(session_id)

    def delete(self, session_id: str) -> None:
        self.get_record(session_id)
        if self.lock_for(session_id).locked():
            raise APIError("SESSION_BUSY", "This conversation is still processing a request.", 409)
        self.store.delete_session(session_id)
        self._live.pop(session_id, None)
        self._persisted_count.pop(session_id, None)
        self._locks.pop(session_id, None)

    def messages(self, session_id: str, limit: int | None = None) -> list[dict[str, Any]]:
        self.get_record(session_id)
        return self.store.list_messages(session_id, limit=limit)

    # Live sessions --------------------------------------------------------------
    def resolve(self, session_id: str | None) -> Session:
        """Return the live Session for an id, creating a new conversation if id is None."""
        if not session_id:
            session_id = self.create()["id"]
        if session_id in self._live:
            return self._live[session_id]
        self.get_record(session_id)
        rows = self.store.list_messages(session_id, limit=HISTORY_LOAD_LIMIT)
        history = []
        for r in rows:
            try:
                history.append(Message(role=Role(r["role"]), content=r["content"], metadata=r["metadata"]))
            except Exception:
                continue
        session = Session(session_id=session_id, user_id=self.user_id, initial_messages=history)
        self._live[session_id] = session
        self._persisted_count[session_id] = len(session.messages)
        return session

    def lock_for(self, session_id: str) -> asyncio.Lock:
        if session_id not in self._locks:
            self._locks[session_id] = asyncio.Lock()
        return self._locks[session_id]

    def persist_new_messages(self, session: Session) -> None:
        """Write messages appended to the live session since the last persist."""
        sid = session.session_id
        start = self._persisted_count.get(sid, 0)
        new = session.messages[start:]
        rows = []
        for m in new:
            meta = dict(m.metadata or {})
            if m.parts:
                meta["attachments"] = [getattr(p, "filename", type(p).__name__) for p in m.parts]
            rows.append((m.role.value, m.content, _safe_metadata(meta)))
        self.store.add_messages(sid, rows)
        self._persisted_count[sid] = len(session.messages)

        record = self.store.get_session(sid)
        if record and record["title"] == DEFAULT_TITLE:
            first_user = next((m for m in session.messages if m.role == Role.USER and m.content.strip()), None)
            if first_user:
                title = " ".join(first_user.content.split())
                self.store.rename_session(sid, title[:60] + ("…" if len(title) > 60 else ""))
