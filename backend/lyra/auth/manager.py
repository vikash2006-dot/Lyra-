"""High-level Authentication and User Identity Manager for LYRA."""

from typing import Any

from lyra.auth.base import AuthProvider
from lyra.core.exceptions import (
    AuthenticationFailedError,
    UserNotFoundError,
)
from lyra.memory.manager import MemoryManager
from lyra.models.identity import AuthResult, User
from lyra.observability.logging import get_logger

logger = get_logger("auth.manager")


class AuthManager:
    """Coordinates authentication, user identity lifecycle, and data privacy operations."""

    def __init__(
        self,
        provider: AuthProvider,
        memory_manager: MemoryManager | None = None,
        scheduler: Any | None = None,
    ) -> None:
        self.provider: AuthProvider = provider
        self.memory_manager: MemoryManager | None = memory_manager
        self.scheduler: Any | None = scheduler

    def register(
        self,
        username: str,
        password: str,
        display_name: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> User:
        """Register a new user identity."""
        return self.provider.register_user(
            username=username,
            password=password,
            display_name=display_name,
            metadata=metadata,
        )

    def login(
        self,
        username: str,
        password: str,
    ) -> tuple[User, str]:
        """Authenticate user credentials.

        Returns:
            Tuple of (User, raw_session_token).

        Raises:
            AuthenticationFailedError: If credentials are invalid or account is locked.
        """
        result: AuthResult = self.provider.authenticate(username, password)
        if not result.success or result.user is None or result.raw_token is None:
            err_msg = result.error_message or "Authentication failed."
            logger.warning("Failed login attempt for username '%s': %s", username, err_msg)
            raise AuthenticationFailedError(err_msg)

        logger.info("User '%s' logged in successfully", result.user.username)
        return result.user, result.raw_token

    def logout(self, raw_token: str) -> bool:
        """Revoke the given session token."""
        if not raw_token:
            return False
        return self.provider.revoke_token(raw_token)

    def validate_session(self, raw_token: str) -> User | None:
        """Validate an active raw session token."""
        return self.provider.validate_token(raw_token)

    def get_user(self, user_id: str) -> User | None:
        """Fetch user by ID."""
        return self.provider.get_user(user_id)

    def get_user_by_username(self, username: str) -> User | None:
        """Fetch user by username."""
        return self.provider.get_user_by_username(username)

    def export_user_data(self, user_id: str) -> dict[str, Any]:
        """Export all data associated with a user identity for transparency and data portability.

        Includes user profile and all long-term memories if memory subsystem is active.
        """
        user = self.provider.get_user(user_id)
        if not user:
            raise UserNotFoundError(f"User with ID '{user_id}' not found.")

        export_data: dict[str, Any] = {
            "user": user.to_dict(),
            "memories": [],
            "automations": [],
        }

        if self.memory_manager is not None:
            memories = self.memory_manager.list_memories(user_id=user_id, limit=1000)
            export_data["memories"] = [m.to_dict() for m in memories]

        if self.scheduler is not None:
            automations = self.scheduler.list_automations(user_id=user_id)
            export_data["automations"] = [a.to_dict() for a in automations]

        logger.info(
            "Exported data for user '%s' (%d memories, %d automations)",
            user_id,
            len(export_data["memories"]),
            len(export_data["automations"]),
        )
        return export_data

    def delete_user_data(self, user_id: str) -> bool:
        """Permanently delete all user data across identity, tokens, long-term memory, and automations."""
        user = self.provider.get_user(user_id)
        if not user:
            raise UserNotFoundError(f"User with ID '{user_id}' not found.")

        purged_memories = 0
        if self.memory_manager is not None:
            purged_memories = self.memory_manager.purge_all(user_id=user_id)

        purged_automations = 0
        if self.scheduler is not None:
            purged_automations = self.scheduler.purge_user(user_id=user_id)

        deleted = self.provider.delete_user(user_id)
        logger.info(
            "Permanently deleted user '%s' (purged %d memories, %d automations)",
            user_id,
            purged_memories,
            purged_automations,
        )
        return deleted
