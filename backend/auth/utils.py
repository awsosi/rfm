"""
Utility functions for password hashing and JWT token management.

Uses Argon2 for password hashing (OWASP recommended) and HS256 for JWT signing.
"""

import os
from datetime import datetime, timedelta, timezone
from typing import Dict, Optional

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import (
    VerifyMismatchError,
    InvalidHashError,
    VerificationError,
)

from auth.exceptions import (
    PasswordHashError,
    InvalidTokenError,
    ExpiredTokenError,
)


# Argon2 password hasher with secure defaults
ph = PasswordHasher(
    time_cost=3,        # Number of iterations
    memory_cost=65536,  # Memory usage in KiB (64 MB)
    parallelism=4,      # Number of parallel threads
    hash_len=32,        # Hash output length
    salt_len=16,        # Salt length
)


def hash_password(password: str) -> str:
    """
    Hash password using Argon2id algorithm.

    Args:
        password: Plain text password to hash

    Returns:
        Argon2 hash string (includes salt and parameters)

    Raises:
        PasswordHashError: If hashing fails

    Example:
        >>> hash_password("admin123")
        '$argon2id$v=19$m=65536,t=3,p=4$...'
    """
    try:
        return ph.hash(password)
    except Exception as exc:
        raise PasswordHashError(f"Failed to hash password: {exc}")


def verify_password(password: str, password_hash: str) -> bool:
    """
    Verify password against Argon2 hash.

    Args:
        password: Plain text password to verify
        password_hash: Argon2 hash to verify against

    Returns:
        True if password matches hash, False otherwise

    Example:
        >>> hash = hash_password("admin123")
        >>> verify_password("admin123", hash)
        True
        >>> verify_password("wrongpass", hash)
        False
    """
    try:
        ph.verify(password_hash, password)
        return True
    except (VerifyMismatchError, InvalidHashError, VerificationError):
        return False
    except Exception:
        return False


def check_needs_rehash(password_hash: str) -> bool:
    """
    Check if password hash needs rehashing (parameters changed).

    Args:
        password_hash: Argon2 hash to check

    Returns:
        True if hash should be regenerated with current parameters

    Example:
        >>> hash = hash_password("admin123")
        >>> check_needs_rehash(hash)
        False
    """
    try:
        return ph.check_needs_rehash(password_hash)
    except Exception:
        return False


def create_jwt_token(
    payload: Dict,
    secret_key: str,
    expires_in_days: int = 30,
    algorithm: str = "HS256",
) -> str:
    """
    Create JWT token with expiration.

    Args:
        payload: Data to encode in token (should include user_id, username, etc.)
        secret_key: Secret key for signing
        expires_in_days: Token lifetime in days
        algorithm: JWT algorithm (default: HS256)

    Returns:
        Encoded JWT token string

    Raises:
        InvalidTokenError: If token creation fails

    Example:
        >>> token = create_jwt_token(
        ...     {"user_id": 1, "username": "admin"},
        ...     "secret",
        ...     expires_in_days=30
        ... )
        >>> isinstance(token, str)
        True
    """
    try:
        # Add standard claims
        now = datetime.now(timezone.utc)
        token_payload = {
            **payload,
            "iat": now,  # Issued at
            "exp": now + timedelta(days=expires_in_days),  # Expiration
        }

        return jwt.encode(token_payload, secret_key, algorithm=algorithm)

    except Exception as exc:
        raise InvalidTokenError(f"Failed to create JWT token: {exc}")


def decode_jwt_token(
    token: str,
    secret_key: str,
    algorithm: str = "HS256",
) -> Dict:
    """
    Decode and verify JWT token.

    Args:
        token: JWT token string to decode
        secret_key: Secret key for verification
        algorithm: JWT algorithm (default: HS256)

    Returns:
        Decoded token payload as dictionary

    Raises:
        ExpiredTokenError: If token has expired
        InvalidTokenError: If token is invalid or verification fails

    Example:
        >>> token = create_jwt_token({"user_id": 1}, "secret")
        >>> payload = decode_jwt_token(token, "secret")
        >>> payload["user_id"]
        1
    """
    try:
        payload = jwt.decode(token, secret_key, algorithms=[algorithm])
        return payload

    except jwt.ExpiredSignatureError:
        raise ExpiredTokenError("JWT token has expired")

    except jwt.InvalidTokenError as exc:
        raise InvalidTokenError(f"Invalid JWT token: {exc}")

    except Exception as exc:
        raise InvalidTokenError(f"Failed to decode JWT token: {exc}")


def get_secret_key(default: Optional[str] = None) -> str:
    """
    Get secret key from environment variable.

    Args:
        default: Default value if SECRET_KEY not set

    Returns:
        Secret key string

    Raises:
        ValueError: If SECRET_KEY not set and no default provided
    """
    secret_key = os.getenv("SECRET_KEY", default)

    if not secret_key:
        raise ValueError(
            "SECRET_KEY environment variable not set. "
            "Generate with: python -c 'import secrets; print(secrets.token_urlsafe(64))'"
        )

    return secret_key


def generate_secret_key(length: int = 64) -> str:
    """
    Generate cryptographically secure secret key.

    Args:
        length: Length of secret in bytes

    Returns:
        URL-safe base64 encoded secret key

    Example:
        >>> key = generate_secret_key(64)
        >>> len(key) > 80
        True
    """
    import secrets
    return secrets.token_urlsafe(length)


def validate_password_strength(password: str) -> tuple[bool, Optional[str]]:
    """
    Validate password meets minimum security requirements.

    Requirements:
    - Minimum 8 characters
    - At least one number (optional, can be configured)
    - At least one letter (optional, can be configured)

    Args:
        password: Password to validate

    Returns:
        Tuple of (is_valid, error_message)

    Example:
        >>> validate_password_strength("admin123")
        (True, None)
        >>> validate_password_strength("short")
        (False, 'Password must be at least 8 characters')
    """
    if len(password) < 8:
        return False, "Password must be at least 8 characters"

    # Additional strength checks can be added here
    # For now, we only enforce minimum length

    return True, None
