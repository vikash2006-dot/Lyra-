"""Cryptographic utilities for password hashing and secure token management in LYRA.

Uses strictly the Python standard library (hashlib, hmac, secrets).
No plaintext passwords or tokens are ever stored or logged.
"""

import hashlib
import hmac
import secrets
from typing import Tuple

from lyra.core.exceptions import PasswordValidationError

# Default scrypt parameters (memory-hard, resistant to GPU/ASIC attacks)
DEFAULT_SCRYPT_N = 16384
DEFAULT_SCRYPT_R = 8
DEFAULT_SCRYPT_P = 1
DEFAULT_SALT_BYTES = 16
MIN_PASSWORD_LENGTH = 6


def validate_password_strength(password: str, min_length: int = MIN_PASSWORD_LENGTH) -> None:
    """Validate password length and non-emptiness before hashing.

    Raises:
        PasswordValidationError: If the password is invalid.
    """
    if not isinstance(password, str):
        raise PasswordValidationError("Password must be a string.")
    if len(password) < min_length:
        raise PasswordValidationError(
            f"Password is too short. Minimum length is {min_length} characters."
        )
    if password.isspace():
        raise PasswordValidationError("Password cannot consist solely of whitespace.")


def hash_password(password: str) -> str:
    """Hash a plaintext password using standard library scrypt with a unique random salt.

    Returns:
        Formatted string: 'scrypt$n$r$p$salt_hex$hash_hex'
    """
    validate_password_strength(password)
    salt = secrets.token_bytes(DEFAULT_SALT_BYTES)

    try:
        derived = hashlib.scrypt(
            password.encode("utf-8"),
            salt=salt,
            n=DEFAULT_SCRYPT_N,
            r=DEFAULT_SCRYPT_R,
            p=DEFAULT_SCRYPT_P,
            maxmem=0,
        )
        return (
            f"scrypt${DEFAULT_SCRYPT_N}${DEFAULT_SCRYPT_R}${DEFAULT_SCRYPT_P}$"
            f"{salt.hex()}${derived.hex()}"
        )
    except (AttributeError, ValueError):
        # Fallback to PBKDF2-HMAC-SHA256 if scrypt is unavailable or restricted
        iterations = 100_000
        derived = hashlib.pbkdf2_hmac(
            "sha256",
            password.encode("utf-8"),
            salt,
            iterations,
        )
        return f"pbkdf2${iterations}${salt.hex()}${derived.hex()}"


def verify_password(password: str, hashed: str) -> bool:
    """Verify a plaintext password against a stored hash using constant-time comparison.

    Supports both 'scrypt' and 'pbkdf2' formatted hashes.
    """
    if not password or not hashed or not isinstance(hashed, str):
        return False

    parts = hashed.split("$")
    if len(parts) < 4:
        return False

    algorithm = parts[0]

    if algorithm == "scrypt":
        if len(parts) != 6:
            return False
        try:
            n = int(parts[1])
            r = int(parts[2])
            p = int(parts[3])
            salt = bytes.fromhex(parts[4])
            expected_hash = bytes.fromhex(parts[5])

            derived = hashlib.scrypt(
                password.encode("utf-8"),
                salt=salt,
                n=n,
                r=r,
                p=p,
                maxmem=0,
            )
            return hmac.compare_digest(derived, expected_hash)
        except Exception:
            return False

    elif algorithm == "pbkdf2":
        if len(parts) != 4:
            return False
        try:
            iterations = int(parts[1])
            salt = bytes.fromhex(parts[2])
            expected_hash = bytes.fromhex(parts[3])

            derived = hashlib.pbkdf2_hmac(
                "sha256",
                password.encode("utf-8"),
                salt,
                iterations,
            )
            return hmac.compare_digest(derived, expected_hash)
        except Exception:
            return False

    return False


def generate_secure_token() -> str:
    """Generate a cryptographically secure, high-entropy raw session token."""
    return secrets.token_urlsafe(32)


def hash_token(raw_token: str) -> str:
    """Hash a raw token using SHA-256 for secure database storage.

    Plaintext tokens are NEVER stored in the database.
    """
    if not raw_token or not isinstance(raw_token, str):
        raise ValueError("Cannot hash empty or invalid token.")
    return hashlib.sha256(raw_token.encode("utf-8")).hexdigest()


def verify_token(raw_token: str, stored_token_hash: str) -> bool:
    """Verify a raw token against a stored SHA-256 hash using constant-time comparison."""
    if not raw_token or not stored_token_hash:
        return False
    computed = hash_token(raw_token)
    return hmac.compare_digest(computed, stored_token_hash)
