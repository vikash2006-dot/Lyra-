"""Abstract base interface for LYRA authentication providers.

Enables pluggable authentication mechanisms (local SQLite, future OAuth, etc.)
without tying LYRA core to any specific provider.
"""

from abc import ABC, abstractmethod
from typing import Any

from lyra.models.identity import AuthResult, User


class AuthProvider(ABC):
    """Abstract authentication provider contract."""

    @abstractmethod
    def register_user(
        self,
        username: str,
        password: str,
        display_name: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> User:
        """Register a new user identity with a hashed password.

        Raises:
            UserAlreadyExistsError: If the username is already registered.
            PasswordValidationError: If the password fails complexity requirements.
            ModelValidationError: If user parameters are malformed.
        """

    @abstractmethod
    def authenticate(
        self,
        username: str,
        password: str,
    ) -> AuthResult:
        """Authenticate a user by username and password.

        Returns:
            AuthResult with success status, User, raw token, or error details.

        Raises:
            AccountLockedError: If account is locked due to excessive failed attempts.
        """

    @abstractmethod
    def validate_token(self, raw_token: str) -> User | None:
        """Validate a raw session token and return the associated User if active and valid."""

    @abstractmethod
    def revoke_token(self, raw_token: str) -> bool:
        """Revoke a session token so it cannot be used again."""

    @abstractmethod
    def get_user(self, user_id: str) -> User | None:
        """Retrieve a User by their unique ID."""

    @abstractmethod
    def get_user_by_username(self, username: str) -> User | None:
        """Retrieve a User by their username."""

    @abstractmethod
    def delete_user(self, user_id: str) -> bool:
        """Permanently delete a user record and revoke all active session tokens."""
