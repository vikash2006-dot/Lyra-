"""Unit tests for LYRA identity and authentication domain models."""

from datetime import datetime, timedelta, timezone
import pytest

from lyra.core.exceptions import ModelValidationError
from lyra.models.identity import (
    AuthResult,
    AuthenticationState,
    AuthToken,
    User,
)


def test_user_creation_and_validation():
    """Verify User model creation, post-init validation, and immutability."""
    user = User(
        id="user-123",
        username="alice",
        display_name="Alice Smith",
        metadata={"role": "member"},
    )
    assert user.id == "user-123"
    assert user.username == "alice"
    assert user.display_name == "Alice Smith"
    assert user.metadata["role"] == "member"
    assert isinstance(user.created_at, datetime)
    assert isinstance(user.updated_at, datetime)

    # Empty ID
    with pytest.raises(ModelValidationError, match="User id"):
        User(id="", username="alice", display_name="Alice")

    # Invalid username (too short or bad chars)
    with pytest.raises(ModelValidationError, match="Invalid username"):
        User(id="123", username="al", display_name="Alice")

    with pytest.raises(ModelValidationError, match="Invalid username"):
        User(id="123", username="alice with spaces", display_name="Alice")

    # Empty display name
    with pytest.raises(ModelValidationError, match="User display_name"):
        User(id="123", username="alice", display_name="")


def test_user_serialization():
    """Verify to_dict and from_dict roundtrip."""
    original = User(
        id="u-456",
        username="bob_jones",
        display_name="Bob Jones",
        metadata={"theme": "dark"},
    )
    data = original.to_dict()
    assert data["id"] == "u-456"
    assert data["username"] == "bob_jones"
    assert data["display_name"] == "Bob Jones"
    assert data["metadata"]["theme"] == "dark"

    reconstructed = User.from_dict(data)
    assert reconstructed.id == original.id
    assert reconstructed.username == original.username
    assert reconstructed.display_name == original.display_name
    assert reconstructed.metadata == original.metadata


def test_auth_token_lifecycle():
    """Verify AuthToken validation, expiry, and revocation checks."""
    now = datetime.now(timezone.utc)
    future = now + timedelta(hours=1)
    past = now - timedelta(hours=1)

    # Valid token
    token = AuthToken(
        token_hash="sha256_hash_here",
        user_id="u-123",
        created_at=now,
        expires_at=future,
        revoked=False,
    )
    assert token.is_valid(now) is True

    # Expired token
    expired_token = AuthToken(
        token_hash="sha256_hash_here",
        user_id="u-123",
        created_at=past - timedelta(hours=1),
        expires_at=past,
        revoked=False,
    )
    assert expired_token.is_valid(now) is False

    # Revoked token
    revoked_token = AuthToken(
        token_hash="sha256_hash_here",
        user_id="u-123",
        created_at=now,
        expires_at=future,
        revoked=True,
    )
    assert revoked_token.is_valid(now) is False

    # Serialization
    token_dict = token.to_dict()
    assert token_dict["token_hash"] == "sha256_hash_here"
    assert token_dict["user_id"] == "u-123"
    assert token_dict["revoked"] is False


def test_auth_result_validation():
    """Verify AuthResult invariants."""
    user = User(id="1", username="testuser", display_name="Test")

    # Valid success
    res_ok = AuthResult(success=True, user=user, raw_token="secret_token")
    assert res_ok.success is True
    assert res_ok.user == user

    # Valid failure
    res_fail = AuthResult(success=False, error_message="Invalid credentials")
    assert res_fail.success is False
    assert res_fail.error_message == "Invalid credentials"

    # Invalid: success without user
    with pytest.raises(ModelValidationError, match="must include a User"):
        AuthResult(success=True, user=None)

    # Invalid: failure without error message
    with pytest.raises(ModelValidationError, match="must include an error_message"):
        AuthResult(success=False, error_message=None)
