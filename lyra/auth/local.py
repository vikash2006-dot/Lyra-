"""Local SQLite implementation of the AuthProvider interface."""

from datetime import datetime, timezone
import json
import sqlite3
import threading
from typing import Any
import uuid

from lyra.auth.base import AuthProvider
from lyra.auth.hasher import (
    generate_secure_token,
    hash_password,
    hash_token,
    verify_password,
)
from lyra.core.exceptions import (
    AccountLockedError,
    AuthError,
    ModelValidationError,
    UserAlreadyExistsError,
    UserNotFoundError,
)
from lyra.models.identity import AuthResult, User
from lyra.observability.logging import get_logger

logger = get_logger("auth.local")


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


class LocalAuthProvider(AuthProvider):
    """Local SQLite-backed authentication provider with secure password and token hashing."""

    def __init__(
        self,
        db_path: str = "lyra_auth.db",
        token_ttl_seconds: float = 86400.0,
        max_failed_attempts: int = 5,
        lockout_duration_seconds: float = 900.0,
    ) -> None:
        self.db_path = db_path
        self.token_ttl_seconds = token_ttl_seconds
        self.max_failed_attempts = max_failed_attempts
        self.lockout_duration_seconds = lockout_duration_seconds
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
                raise AuthError(f"Failed to connect to SQLite auth database: {err}") from err
        return self._conn

    def _init_db(self) -> None:
        """Initialize authentication tables and indices."""
        with self._lock:
            conn = self._get_connection()
            try:
                with conn:
                    conn.execute("""
                        CREATE TABLE IF NOT EXISTS users (
                            id TEXT PRIMARY KEY,
                            username TEXT UNIQUE NOT NULL,
                            password_hash TEXT NOT NULL,
                            display_name TEXT NOT NULL,
                            created_at TEXT NOT NULL,
                            updated_at TEXT NOT NULL,
                            metadata_json TEXT NOT NULL,
                            failed_attempts INTEGER NOT NULL DEFAULT 0,
                            locked_until TEXT
                        )
                    """)
                    conn.execute("""
                        CREATE TABLE IF NOT EXISTS auth_tokens (
                            token_hash TEXT PRIMARY KEY,
                            user_id TEXT NOT NULL,
                            created_at TEXT NOT NULL,
                            expires_at TEXT NOT NULL,
                            revoked INTEGER NOT NULL DEFAULT 0,
                            FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
                        )
                    """)
                    conn.execute("""
                        CREATE INDEX IF NOT EXISTS idx_users_username
                        ON users(username)
                    """)
                    conn.execute("""
                        CREATE INDEX IF NOT EXISTS idx_tokens_user_id
                        ON auth_tokens(user_id)
                    """)
            except sqlite3.Error as err:
                raise AuthError(f"Failed to initialize auth tables: {err}") from err

    def register_user(
        self,
        username: str,
        password: str,
        display_name: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> User:
        """Register a new user identity with a hashed password."""
        norm_username = username.strip().lower()
        if not norm_username:
            raise ModelValidationError("Username cannot be empty.")

        display = (display_name or norm_username).strip()
        user_id = str(uuid.uuid4())
        hashed_pw = hash_password(password)
        now = _utc_now()
        meta = dict(metadata) if metadata else {}

        user = User(
            id=user_id,
            username=norm_username,
            display_name=display,
            created_at=now,
            updated_at=now,
            metadata=meta,
        )

        with self._lock:
            conn = self._get_connection()
            try:
                with conn:
                    # Check if username already exists
                    cursor = conn.execute(
                        "SELECT id FROM users WHERE username = ?",
                        (norm_username,),
                    )
                    if cursor.fetchone():
                        raise UserAlreadyExistsError(
                            f"Username '{norm_username}' is already registered."
                        )

                    conn.execute(
                        """
                        INSERT INTO users (
                            id, username, password_hash, display_name,
                            created_at, updated_at, metadata_json,
                            failed_attempts, locked_until
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, 0, NULL)
                        """,
                        (
                            user.id,
                            user.username,
                            hashed_pw,
                            user.display_name,
                            user.created_at.isoformat(),
                            user.updated_at.isoformat(),
                            json.dumps(user.metadata),
                        ),
                    )
            except sqlite3.IntegrityError as err:
                raise UserAlreadyExistsError(
                    f"Username '{norm_username}' is already registered."
                ) from err
            except sqlite3.Error as err:
                raise AuthError(f"Failed to register user: {err}") from err

        logger.info("Registered new user '%s' (%s)", norm_username, user_id)
        return user

    def authenticate(
        self,
        username: str,
        password: str,
    ) -> AuthResult:
        """Authenticate a user by username and password.

        Returns:
            AuthResult containing User and raw token if successful, or error message.
        """
        norm_username = username.strip().lower()
        now = _utc_now()

        with self._lock:
            conn = self._get_connection()
            try:
                with conn:
                    cursor = conn.execute(
                        """
                        SELECT id, username, password_hash, display_name,
                               created_at, updated_at, metadata_json,
                               failed_attempts, locked_until
                        FROM users
                        WHERE username = ?
                        """,
                        (norm_username,),
                    )
                    row = cursor.fetchone()
                    if not row:
                        return AuthResult(
                            success=False,
                            error_message="Invalid username or password.",
                        )

                    user_id = row["id"]
                    failed_attempts = row["failed_attempts"]
                    locked_until_str = row["locked_until"]

                    # Check lockout
                    if locked_until_str:
                        locked_until = datetime.fromisoformat(locked_until_str)
                        if locked_until.tzinfo is None:
                            locked_until = locked_until.replace(tzinfo=timezone.utc)
                        if now < locked_until:
                            return AuthResult(
                                success=False,
                                error_message=(
                                    "Account is temporarily locked due to excessive failed attempts. "
                                    f"Try again after {locked_until_str}."
                                ),
                            )
                        # Lockout expired, reset
                        failed_attempts = 0
                        conn.execute(
                            "UPDATE users SET failed_attempts = 0, locked_until = NULL WHERE id = ?",
                            (user_id,),
                        )

                    # Verify password
                    password_valid = verify_password(password, row["password_hash"])
                    if not password_valid:
                        new_failed = failed_attempts + 1
                        new_locked_until = None
                        error_msg = "Invalid username or password."

                        if new_failed >= self.max_failed_attempts:
                            lockout_time = datetime.fromtimestamp(
                                now.timestamp() + self.lockout_duration_seconds,
                                tz=timezone.utc,
                            )
                            new_locked_until = lockout_time.isoformat()
                            error_msg = (
                                "Account is temporarily locked due to excessive failed attempts. "
                                f"Try again after {new_locked_until}."
                            )

                        conn.execute(
                            """
                            UPDATE users
                            SET failed_attempts = ?, locked_until = ?, updated_at = ?
                            WHERE id = ?
                            """,
                            (new_failed, new_locked_until, now.isoformat(), user_id),
                        )
                        return AuthResult(success=False, error_message=error_msg)

                    # Password is valid -> reset failed attempts and generate token
                    conn.execute(
                        """
                        UPDATE users
                        SET failed_attempts = 0, locked_until = NULL, updated_at = ?
                        WHERE id = ?
                        """,
                        (now.isoformat(), user_id),
                    )

                    raw_token = generate_secure_token()
                    thash = hash_token(raw_token)
                    expires_at = datetime.fromtimestamp(
                        now.timestamp() + self.token_ttl_seconds,
                        tz=timezone.utc,
                    )

                    conn.execute(
                        """
                        INSERT INTO auth_tokens (token_hash, user_id, created_at, expires_at, revoked)
                        VALUES (?, ?, ?, ?, 0)
                        """,
                        (thash, user_id, now.isoformat(), expires_at.isoformat()),
                    )

                    user = User(
                        id=user_id,
                        username=row["username"],
                        display_name=row["display_name"],
                        created_at=datetime.fromisoformat(row["created_at"]),
                        updated_at=now,
                        metadata=json.loads(row["metadata_json"]),
                    )

                    logger.info("User '%s' authenticated successfully", norm_username)
                    return AuthResult(success=True, user=user, raw_token=raw_token)

            except sqlite3.Error as err:
                raise AuthError(f"Database error during authentication: {err}") from err

    def validate_token(self, raw_token: str) -> User | None:
        """Validate a raw session token and return the associated User if active and valid."""
        if not raw_token or not isinstance(raw_token, str):
            return None

        thash = hash_token(raw_token)
        now = _utc_now()

        with self._lock:
            conn = self._get_connection()
            try:
                cursor = conn.execute(
                    """
                    SELECT t.token_hash, t.user_id, t.expires_at, t.revoked,
                           u.username, u.display_name, u.created_at, u.updated_at, u.metadata_json
                    FROM auth_tokens t
                    JOIN users u ON t.user_id = u.id
                    WHERE t.token_hash = ? AND t.revoked = 0
                    """,
                    (thash,),
                )
                row = cursor.fetchone()
                if not row:
                    return None

                expires_at = datetime.fromisoformat(row["expires_at"])
                if expires_at.tzinfo is None:
                    expires_at = expires_at.replace(tzinfo=timezone.utc)

                if now >= expires_at:
                    return None

                return User(
                    id=row["user_id"],
                    username=row["username"],
                    display_name=row["display_name"],
                    created_at=datetime.fromisoformat(row["created_at"]),
                    updated_at=datetime.fromisoformat(row["updated_at"]),
                    metadata=json.loads(row["metadata_json"]),
                )
            except sqlite3.Error as err:
                logger.error("Error validating auth token: %s", err)
                return None

    def revoke_token(self, raw_token: str) -> bool:
        """Revoke a session token so it cannot be used again."""
        if not raw_token or not isinstance(raw_token, str):
            return False

        thash = hash_token(raw_token)
        with self._lock:
            conn = self._get_connection()
            try:
                with conn:
                    cursor = conn.execute(
                        "UPDATE auth_tokens SET revoked = 1 WHERE token_hash = ?",
                        (thash,),
                    )
                    return cursor.rowcount > 0
            except sqlite3.Error as err:
                logger.error("Error revoking token: %s", err)
                return False

    def revoke_all_user_tokens(self, user_id: str) -> int:
        """Revoke all active tokens for a specific user (e.g. on password change or full logout)."""
        with self._lock:
            conn = self._get_connection()
            try:
                with conn:
                    cursor = conn.execute(
                        "UPDATE auth_tokens SET revoked = 1 WHERE user_id = ? AND revoked = 0",
                        (user_id,),
                    )
                    return cursor.rowcount
            except sqlite3.Error as err:
                logger.error("Error revoking user tokens: %s", err)
                return 0

    def get_user(self, user_id: str) -> User | None:
        """Retrieve a User by unique user ID."""
        with self._lock:
            conn = self._get_connection()
            cursor = conn.execute(
                """
                SELECT id, username, display_name, created_at, updated_at, metadata_json
                FROM users WHERE id = ?
                """,
                (user_id,),
            )
            row = cursor.fetchone()
            if not row:
                return None
            return User(
                id=row["id"],
                username=row["username"],
                display_name=row["display_name"],
                created_at=datetime.fromisoformat(row["created_at"]),
                updated_at=datetime.fromisoformat(row["updated_at"]),
                metadata=json.loads(row["metadata_json"]),
            )

    def get_user_by_username(self, username: str) -> User | None:
        """Retrieve a User by username."""
        norm_username = username.strip().lower()
        with self._lock:
            conn = self._get_connection()
            cursor = conn.execute(
                """
                SELECT id, username, display_name, created_at, updated_at, metadata_json
                FROM users WHERE username = ?
                """,
                (norm_username,),
            )
            row = cursor.fetchone()
            if not row:
                return None
            return User(
                id=row["id"],
                username=row["username"],
                display_name=row["display_name"],
                created_at=datetime.fromisoformat(row["created_at"]),
                updated_at=datetime.fromisoformat(row["updated_at"]),
                metadata=json.loads(row["metadata_json"]),
            )

    def delete_user(self, user_id: str) -> bool:
        """Permanently delete a user and all their associated tokens."""
        with self._lock:
            conn = self._get_connection()
            try:
                with conn:
                    conn.execute("DELETE FROM auth_tokens WHERE user_id = ?", (user_id,))
                    cursor = conn.execute("DELETE FROM users WHERE id = ?", (user_id,))
                    deleted = cursor.rowcount > 0
                    if deleted:
                        logger.info("Deleted user account '%s'", user_id)
                    return deleted
            except sqlite3.Error as err:
                raise AuthError(f"Failed to delete user: {err}") from err
