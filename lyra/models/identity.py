"""Canonical domain models for LYRA identity and authentication."""

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
import re
from typing import Any
import uuid

from lyra.core.exceptions import ModelValidationError


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


class AuthenticationState(str, Enum):
    """Lifecycle states of user authentication."""

    ANONYMOUS = "anonymous"
    AUTHENTICATED = "authenticated"
    EXPIRED = "expired"
    LOCKED = "locked"


USERNAME_REGEX = re.compile(r"^[a-zA-Z0-9_\-\.]{3,32}$")


@dataclass(frozen=True)
class User:
    """Canonical domain model for an authenticated LYRA user."""

    id: str
    username: str
    display_name: str
    created_at: datetime = field(default_factory=_utc_now)
    updated_at: datetime = field(default_factory=_utc_now)
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.id or not isinstance(self.id, str) or not self.id.strip():
            raise ModelValidationError("User id must be a non-empty string.")
        if not self.username or not isinstance(self.username, str) or not self.username.strip():
            raise ModelValidationError("User username must be a non-empty string.")
        norm_username = self.username.strip()
        if not USERNAME_REGEX.match(norm_username):
            raise ModelValidationError(
                f"Invalid username '{norm_username}'. Must be 3-32 chars alphanumeric, underscore, hyphen, or dot."
            )
        if not self.display_name or not isinstance(self.display_name, str) or not self.display_name.strip():
            raise ModelValidationError("User display_name must be a non-empty string.")

    def to_dict(self) -> dict[str, Any]:
        """Convert User model to dictionary representation."""
        return {
            "id": self.id,
            "username": self.username,
            "display_name": self.display_name,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
            "metadata": dict(self.metadata),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "User":
        """Reconstruct User model from dictionary representation."""
        created_str = data.get("created_at")
        updated_str = data.get("updated_at")

        created_at = (
            datetime.fromisoformat(created_str)
            if created_str
            else _utc_now()
        )
        updated_at = (
            datetime.fromisoformat(updated_str)
            if updated_str
            else created_at
        )

        return cls(
            id=data["id"],
            username=data["username"],
            display_name=data.get("display_name", data["username"]),
            created_at=created_at,
            updated_at=updated_at,
            metadata=dict(data.get("metadata", {})),
        )


@dataclass(frozen=True)
class AuthToken:
    """Canonical model for a hashed session token."""

    token_hash: str
    user_id: str
    created_at: datetime = field(default_factory=_utc_now)
    expires_at: datetime = field(default_factory=_utc_now)
    revoked: bool = False

    def __post_init__(self) -> None:
        if not self.token_hash or not isinstance(self.token_hash, str) or not self.token_hash.strip():
            raise ModelValidationError("AuthToken token_hash must be a non-empty string.")
        if not self.user_id or not isinstance(self.user_id, str) or not self.user_id.strip():
            raise ModelValidationError("AuthToken user_id must be a non-empty string.")

    def is_valid(self, current_time: datetime | None = None) -> bool:
        """Check if this token is currently active and unexpired."""
        if self.revoked:
            return False
        now = current_time or _utc_now()
        exp = self.expires_at if self.expires_at.tzinfo else self.expires_at.replace(tzinfo=timezone.utc)
        curr = now if now.tzinfo else now.replace(tzinfo=timezone.utc)
        return curr < exp

    def to_dict(self) -> dict[str, Any]:
        """Convert token record to dictionary."""
        return {
            "token_hash": self.token_hash,
            "user_id": self.user_id,
            "created_at": self.created_at.isoformat(),
            "expires_at": self.expires_at.isoformat(),
            "revoked": self.revoked,
        }


@dataclass(frozen=True)
class AuthResult:
    """Outcome of an authentication attempt."""

    success: bool
    user: User | None = None
    raw_token: str | None = None
    error_message: str | None = None

    def __post_init__(self) -> None:
        if self.success and self.user is None:
            raise ModelValidationError("Successful AuthResult must include a User.")
        if not self.success and not self.error_message:
            raise ModelValidationError("Unsuccessful AuthResult must include an error_message.")
