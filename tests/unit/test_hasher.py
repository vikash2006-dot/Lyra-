"""Unit tests for LYRA password hashing and token cryptography."""

import pytest

from lyra.auth.hasher import (
    generate_secure_token,
    hash_password,
    hash_token,
    validate_password_strength,
    verify_password,
    verify_token,
)
from lyra.core.exceptions import PasswordValidationError


def test_validate_password_strength():
    """Verify password strength validation rules."""
    # Valid passwords
    validate_password_strength("secret123")
    validate_password_strength("a" * 20)

    # Too short
    with pytest.raises(PasswordValidationError, match="too short"):
        validate_password_strength("abc")

    # Non-string
    with pytest.raises(PasswordValidationError, match="must be a string"):
        validate_password_strength(12345678)  # type: ignore

    # Solely whitespace
    with pytest.raises(PasswordValidationError, match="solely of whitespace"):
        validate_password_strength("       ")


def test_hash_password_and_verification():
    """Verify scrypt password hashing and constant-time verification."""
    pw = "CorrectBatteryStaple#42"
    hashed = hash_password(pw)

    # Must not contain plaintext password
    assert pw not in hashed
    assert hashed.startswith("scrypt$") or hashed.startswith("pbkdf2$")

    # Valid verification
    assert verify_password(pw, hashed) is True

    # Invalid verification
    assert verify_password("WrongPassword", hashed) is False
    assert verify_password("", hashed) is False
    assert verify_password(pw, "") is False
    assert verify_password(pw, "malformed_hash") is False


def test_hash_password_generates_unique_salts():
    """Verify two hashes of the same password produce distinct salt/hash outputs."""
    pw = "SuperSecurePassword123"
    hash1 = hash_password(pw)
    hash2 = hash_password(pw)

    assert hash1 != hash2
    assert verify_password(pw, hash1) is True
    assert verify_password(pw, hash2) is True


def test_secure_tokens_and_hashing():
    """Verify token generation, SHA-256 hashing, and constant-time verification."""
    token1 = generate_secure_token()
    token2 = generate_secure_token()

    assert token1 != token2
    assert len(token1) >= 32

    hash1 = hash_token(token1)
    hash2 = hash_token(token2)

    assert hash1 != hash2
    assert len(hash1) == 64  # SHA-256 hex digest length

    # Verification
    assert verify_token(token1, hash1) is True
    assert verify_token(token2, hash2) is True
    assert verify_token(token1, hash2) is False
    assert verify_token("", hash1) is False
    assert verify_token(token1, "") is False
