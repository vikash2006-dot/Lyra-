"""SQLite persistent implementation of AutomationStore."""

from datetime import datetime, timezone
import json
import sqlite3
import threading
from typing import Any

from lyra.automation.store import AutomationStore
from lyra.core.exceptions import AutomationError
from lyra.models.automation import Action, Automation, Trigger
from lyra.observability.logging import get_logger

logger = get_logger("automation.store")


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


class SQLiteAutomationStore(AutomationStore):
    """SQLite-backed automation store ensuring data survives application restarts."""

    def __init__(self, db_path: str = "lyra_automation.db") -> None:
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
            except sqlite3.Error as err:
                raise AutomationError(f"Failed to connect to SQLite automation database: {err}") from err
        return self._conn

    def _init_db(self) -> None:
        """Initialize database schema and indices."""
        with self._lock:
            conn = self._get_connection()
            try:
                with conn:
                    conn.execute("""
                        CREATE TABLE IF NOT EXISTS automations (
                            id TEXT PRIMARY KEY,
                            user_id TEXT NOT NULL,
                            name TEXT NOT NULL,
                            description TEXT NOT NULL,
                            trigger_json TEXT NOT NULL,
                            action_json TEXT NOT NULL,
                            enabled INTEGER NOT NULL DEFAULT 1,
                            created_at TEXT NOT NULL,
                            updated_at TEXT NOT NULL,
                            next_run TEXT,
                            last_run TEXT,
                            consecutive_failures INTEGER NOT NULL DEFAULT 0,
                            last_error TEXT,
                            max_retries INTEGER NOT NULL DEFAULT 3
                        )
                    """)
                    conn.execute("""
                        CREATE INDEX IF NOT EXISTS idx_automations_user_id
                        ON automations(user_id)
                    """)
                    conn.execute("""
                        CREATE INDEX IF NOT EXISTS idx_automations_due
                        ON automations(enabled, next_run)
                    """)
            except sqlite3.Error as err:
                raise AutomationError(f"Failed to initialize automation schema: {err}") from err

    def _row_to_automation(self, row: sqlite3.Row) -> Automation:
        trigger_dict = json.loads(row["trigger_json"])
        action_dict = json.loads(row["action_json"])
        trigger = Trigger.from_dict(trigger_dict)
        action = Action.from_dict(action_dict)

        created_at = datetime.fromisoformat(row["created_at"])
        updated_at = datetime.fromisoformat(row["updated_at"])
        next_run = datetime.fromisoformat(row["next_run"]) if row["next_run"] else None
        last_run = datetime.fromisoformat(row["last_run"]) if row["last_run"] else None

        return Automation(
            id=row["id"],
            user_id=row["user_id"],
            name=row["name"],
            description=row["description"],
            trigger=trigger,
            action=action,
            enabled=bool(row["enabled"]),
            created_at=created_at,
            updated_at=updated_at,
            next_run=next_run,
            last_run=last_run,
            consecutive_failures=row["consecutive_failures"],
            last_error=row["last_error"],
            max_retries=row["max_retries"],
        )

    def save(self, automation: Automation) -> None:
        """Insert or update an automation task in storage."""
        with self._lock:
            conn = self._get_connection()
            try:
                with conn:
                    conn.execute(
                        """
                        INSERT INTO automations (
                            id, user_id, name, description,
                            trigger_json, action_json, enabled,
                            created_at, updated_at, next_run, last_run,
                            consecutive_failures, last_error, max_retries
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        ON CONFLICT(id) DO UPDATE SET
                            user_id=excluded.user_id,
                            name=excluded.name,
                            description=excluded.description,
                            trigger_json=excluded.trigger_json,
                            action_json=excluded.action_json,
                            enabled=excluded.enabled,
                            updated_at=excluded.updated_at,
                            next_run=excluded.next_run,
                            last_run=excluded.last_run,
                            consecutive_failures=excluded.consecutive_failures,
                            last_error=excluded.last_error,
                            max_retries=excluded.max_retries
                        """,
                        (
                            automation.id,
                            automation.user_id,
                            automation.name,
                            automation.description,
                            json.dumps(automation.trigger.to_dict()),
                            json.dumps(automation.action.to_dict()),
                            1 if automation.enabled else 0,
                            automation.created_at.isoformat(),
                            automation.updated_at.isoformat(),
                            automation.next_run.isoformat() if automation.next_run else None,
                            automation.last_run.isoformat() if automation.last_run else None,
                            automation.consecutive_failures,
                            automation.last_error,
                            automation.max_retries,
                        ),
                    )
            except sqlite3.Error as err:
                raise AutomationError(f"Failed to save automation '{automation.id}': {err}") from err

    def get(self, automation_id: str, user_id: str | None = None) -> Automation | None:
        """Retrieve an automation by ID, optionally validating user ownership."""
        with self._lock:
            conn = self._get_connection()
            try:
                if user_id:
                    cursor = conn.execute(
                        "SELECT * FROM automations WHERE id = ? AND user_id = ?",
                        (automation_id, user_id),
                    )
                else:
                    cursor = conn.execute(
                        "SELECT * FROM automations WHERE id = ?",
                        (automation_id, user_id if user_id else automation_id),
                        # Wait! For no user_id:
                    )
            except sqlite3.Error:
                pass
        # Let's write the query cleanly without tuple indexing bug:
        with self._lock:
            conn = self._get_connection()
            try:
                if user_id:
                    cursor = conn.execute(
                        "SELECT * FROM automations WHERE id = ? AND user_id = ?",
                        (automation_id, user_id),
                    )
                else:
                    cursor = conn.execute(
                        "SELECT * FROM automations WHERE id = ?",
                        (automation_id,),
                    )
                row = cursor.fetchone()
                if not row:
                    return None
                return self._row_to_automation(row)
            except sqlite3.Error as err:
                raise AutomationError(f"Failed to get automation '{automation_id}': {err}") from err

    def list_automations(
        self,
        user_id: str | None = None,
        enabled_only: bool = False,
    ) -> list[Automation]:
        """List stored automations, optionally filtered by user and enabled state."""
        query = "SELECT * FROM automations WHERE 1=1"
        params: list[Any] = []

        if user_id:
            query += " AND user_id = ?"
            params.append(user_id)
        if enabled_only:
            query += " AND enabled = 1"

        query += " ORDER BY created_at ASC"

        with self._lock:
            conn = self._get_connection()
            try:
                cursor = conn.execute(query, params)
                rows = cursor.fetchall()
                return [self._row_to_automation(r) for r in rows]
            except sqlite3.Error as err:
                raise AutomationError(f"Failed to list automations: {err}") from err

    def delete(self, automation_id: str, user_id: str | None = None) -> bool:
        """Delete an automation from storage."""
        with self._lock:
            conn = self._get_connection()
            try:
                with conn:
                    if user_id:
                        cursor = conn.execute(
                            "DELETE FROM automations WHERE id = ? AND user_id = ?",
                            (automation_id, user_id),
                        )
                    else:
                        cursor = conn.execute(
                            "DELETE FROM automations WHERE id = ?",
                            (automation_id,),
                        )
                    return cursor.rowcount > 0
            except sqlite3.Error as err:
                raise AutomationError(f"Failed to delete automation '{automation_id}': {err}") from err

    def get_due_automations(self, as_of: datetime | None = None) -> list[Automation]:
        """Retrieve all enabled automations whose next_run is on or before as_of."""
        ref = as_of or _utc_now()
        ref_iso = ref.astimezone(timezone.utc).isoformat()

        with self._lock:
            conn = self._get_connection()
            try:
                cursor = conn.execute(
                    """
                    SELECT * FROM automations
                    WHERE enabled = 1 AND next_run IS NOT NULL AND next_run <= ?
                    ORDER BY next_run ASC
                    """,
                    (ref_iso,),
                )
                rows = cursor.fetchall()
                return [self._row_to_automation(r) for r in rows]
            except sqlite3.Error as err:
                raise AutomationError(f"Failed to get due automations: {err}") from err

    def purge_user(self, user_id: str) -> int:
        """Delete all automations belonging to a specific user (for data privacy)."""
        with self._lock:
            conn = self._get_connection()
            try:
                with conn:
                    cursor = conn.execute(
                        "DELETE FROM automations WHERE user_id = ?",
                        (user_id,),
                    )
                    count = cursor.rowcount
                    logger.info("Purged %d automations for user '%s'", count, user_id)
                    return count
            except sqlite3.Error as err:
                raise AutomationError(f"Failed to purge user automations: {err}") from err
