"""Unit tests for LocalAuthProvider (SQLite implementation)."""

import time
import pytest

from lyra.auth.local import LocalAuthProvider
from lyra.core.exceptions import UserAlreadyExistsError


@pytest.fixture
def auth_provider(tmp_path):
    """Provide a fresh LocalAuthProvider with temporary SQLite database."""
    db_file = str(tmp_path / "test_auth.db")
    return LocalAuthProvider(
        db_path=db_file,
        token_ttl_seconds=2.0,  # short TTL for expiration tests
        max_failed_attempts=3,
        lockout_duration_seconds=1.0,
    )


def test_user_registration(auth_provider):
    """Verify user registration and profile lookup."""
    user = auth_provider.register_user(
        username="alice",
        password="ValidPassword123",
        display_name="Alice Wonderland",
        metadata={"preferred_lang": "en"},
    )
    assert user.username == "alice"
    assert user.display_name == "Alice Wonderland"
    assert user.metadata["preferred_lang"] == "en"

    # Lookup by ID and username
    fetched_by_id = auth_provider.get_user(user.id)
    assert fetched_by_id is not None
    assert fetched_by_id.username == "alice"

    fetched_by_name = auth_provider.get_user_by_username("alice")
    assert fetched_by_name is not None
    assert fetched_by_name.id == user.id


def test_duplicate_registration_raises_error(auth_provider):
    """Verify that registering duplicate username raises UserAlreadyExistsError."""
    auth_provider.register_user(username="bob", password="Password123")

    with pytest.raises(UserAlreadyExistsError, match="already registered"):
        auth_provider.register_user(username="bob", password="AnotherPassword456")

    # Case insensitivity check
    with pytest.raises(UserAlreadyExistsError, match="already registered"):
        auth_provider.register_user(username="BOB", password="AnotherPassword456")


def test_successful_authentication_and_token_validation(auth_provider):
    """Verify successful login returns valid token and User."""
    auth_provider.register_user(username="charlie", password="SecureCharliePassword")

    res = auth_provider.authenticate(username="charlie", password="SecureCharliePassword")
    assert res.success is True
    assert res.user is not None
    assert res.user.username == "charlie"
    assert res.raw_token is not None

    # Validate token
    validated_user = auth_provider.validate_token(res.raw_token)
    assert validated_user is not None
    assert validated_user.id == res.user.id


def test_authentication_invalid_credentials(auth_provider):
    """Verify authentication with invalid password or non-existent user."""
    auth_provider.register_user(username="david", password="DavidPassword123")

    # Wrong password
    res_wrong_pw = auth_provider.authenticate(username="david", password="WrongPassword")
    assert res_wrong_pw.success is False
    assert "Invalid username or password" in res_wrong_pw.error_message

    # Non-existent user
    res_no_user = auth_provider.authenticate(username="unknown_user", password="AnyPassword")
    assert res_no_user.success is False
    assert "Invalid username or password" in res_no_user.error_message


def test_account_lockout_and_recovery(auth_provider):
    """Verify account locks after max failed attempts and recovers after cooldown."""
    auth_provider.register_user(username="eve", password="EvePassword123")

    # 1st failed attempt
    res1 = auth_provider.authenticate(username="eve", password="wrong")
    assert res1.success is False

    # 2nd failed attempt
    res2 = auth_provider.authenticate(username="eve", password="wrong")
    assert res2.success is False

    # 3rd failed attempt -> triggers lockout
    res3 = auth_provider.authenticate(username="eve", password="wrong")
    assert res3.success is False
    assert "locked" in res3.error_message.lower()

    # Immediate attempt with correct password must still be rejected due to lockout
    res_locked = auth_provider.authenticate(username="eve", password="EvePassword123")
    assert res_locked.success is False
    assert "locked" in res_locked.error_message.lower()

    # Wait for lockout to expire (1.1s)
    time.sleep(1.1)

    # Now login with correct password should succeed and clear lockout
    res_recovered = auth_provider.authenticate(username="eve", password="EvePassword123")
    assert res_recovered.success is True
    assert res_recovered.user.username == "eve"


def test_session_token_expiration(auth_provider):
    """Verify expired tokens are rejected."""
    auth_provider.register_user(username="frank", password="FrankPassword123")
    res = auth_provider.authenticate(username="frank", password="FrankPassword123")
    token = res.raw_token

    # Token should be initially valid
    assert auth_provider.validate_token(token) is not None

    # Wait for TTL to expire (2.0s TTL in fixture)
    time.sleep(2.1)

    # Expired token must return None
    assert auth_provider.validate_token(token) is None


def test_session_token_revocation_on_logout(auth_provider):
    """Verify token revocation (logout)."""
    auth_provider.register_user(username="grace", password="GracePassword123")
    res = auth_provider.authenticate(username="grace", password="GracePassword123")
    token = res.raw_token

    assert auth_provider.validate_token(token) is not None

    # Revoke token
    revoked = auth_provider.revoke_token(token)
    assert revoked is True

    # Revoked token must return None
    assert auth_provider.validate_token(token) is None


def test_user_deletion(auth_provider):
    """Verify user deletion removes profile and tokens."""
    user = auth_provider.register_user(username="heidi", password="HeidiPassword123")
    res = auth_provider.authenticate(username="heidi", password="HeidiPassword123")
    token = res.raw_token

    assert auth_provider.validate_token(token) is not None

    # Delete user
    deleted = auth_provider.delete_user(user.id)
    assert deleted is True

    # Verify user and token no longer exist
    assert auth_provider.get_user(user.id) is None
    assert auth_provider.validate_token(token) is None
