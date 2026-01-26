"""
Unit tests for authentication module.

Tests all authentication functionality including:
- Password hashing and verification
- Session creation and verification
- Local database authentication
- Admin emergency login
- External API integration (mocked)
"""

import os
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import httpx
from sqlalchemy.ext.asyncio import AsyncSession

from auth.authenticator import (
    Authenticator,
    verify_password,
    hash_password,
    create_session,
    verify_session,
)
from auth.exceptions import (
    InvalidCredentialsError,
    UserNotFoundError,
    UserDisabledError,
    ExpiredTokenError,
    InvalidTokenError,
    SessionNotFoundError,
    ExternalAuthTimeoutError,
)
from auth.utils import (
    hash_password as _hash_password,
    verify_password as _verify_password,
    create_jwt_token,
    decode_jwt_token,
    validate_password_strength,
)
from models import User, Session as SessionModel, UserRole


# Test fixtures

@pytest.fixture
def secret_key():
    """Test secret key."""
    return "test-secret-key-for-jwt-signing-minimum-32-chars-long"


@pytest.fixture
async def test_user(db_session: AsyncSession):
    """Create test user in database."""
    password_hash = _hash_password("testpass123")

    user = User(
        username="testuser",
        password_hash=password_hash,
        role=UserRole.USER,
        is_active=True,
    )

    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)

    return user


@pytest.fixture
async def disabled_user(db_session: AsyncSession):
    """Create disabled test user."""
    user = User(
        username="disabled",
        password_hash=_hash_password("pass123"),
        role=UserRole.USER,
        is_active=False,
    )

    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)

    return user


@pytest.fixture
def authenticator(db_session: AsyncSession, secret_key: str):
    """Create authenticator instance."""
    return Authenticator(
        db=db_session,
        secret_key=secret_key,
        external_auth_enabled=False,
    )


# Password hashing tests

def test_hash_password():
    """Test password hashing."""
    password = "test123"
    hash1 = _hash_password(password)
    hash2 = _hash_password(password)

    # Hashes should be different (due to salt)
    assert hash1 != hash2

    # Both should start with Argon2 prefix
    assert hash1.startswith("$argon2id$")
    assert hash2.startswith("$argon2id$")


def test_verify_password_valid():
    """Test password verification with valid password."""
    password = "test123"
    password_hash = _hash_password(password)

    assert _verify_password(password, password_hash) is True


def test_verify_password_invalid():
    """Test password verification with invalid password."""
    password = "test123"
    password_hash = _hash_password(password)

    assert _verify_password("wrongpass", password_hash) is False


def test_password_strength_validation():
    """Test password strength validation."""
    # Valid passwords
    assert validate_password_strength("test1234")[0] is True
    assert validate_password_strength("LongPassword123")[0] is True

    # Invalid passwords (too short)
    valid, error = validate_password_strength("short")
    assert valid is False
    assert "8 characters" in error


# JWT token tests

def test_create_jwt_token(secret_key: str):
    """Test JWT token creation."""
    payload = {"user_id": 1, "username": "test"}

    token = create_jwt_token(payload, secret_key, expires_in_days=30)

    assert isinstance(token, str)
    assert len(token) > 0


def test_decode_jwt_token(secret_key: str):
    """Test JWT token decoding."""
    payload = {"user_id": 1, "username": "test"}
    token = create_jwt_token(payload, secret_key)

    decoded = decode_jwt_token(token, secret_key)

    assert decoded["user_id"] == 1
    assert decoded["username"] == "test"
    assert "iat" in decoded
    assert "exp" in decoded


def test_decode_invalid_jwt_token(secret_key: str):
    """Test decoding invalid JWT token."""
    with pytest.raises(InvalidTokenError):
        decode_jwt_token("invalid.token.here", secret_key)


def test_decode_expired_jwt_token(secret_key: str):
    """Test decoding expired JWT token."""
    # Create token that expired 1 day ago
    payload = {
        "user_id": 1,
        "exp": datetime.now(timezone.utc) - timedelta(days=1),
    }

    token = create_jwt_token(payload, secret_key, expires_in_days=-1)

    with pytest.raises(ExpiredTokenError):
        decode_jwt_token(token, secret_key)


# Admin emergency login tests

@pytest.mark.asyncio
async def test_admin_emergency_login(authenticator: Authenticator):
    """Test admin emergency login with .env credentials."""
    # Default admin credentials
    result = await authenticator.verify_password("admin", "admin123")

    assert result is True


@pytest.mark.asyncio
async def test_admin_emergency_login_wrong_password(authenticator: Authenticator):
    """Test admin emergency login with wrong password."""
    with pytest.raises(InvalidCredentialsError):
        await authenticator.verify_password("admin", "wrongpass")


# Local database authentication tests

@pytest.mark.asyncio
async def test_verify_password_local_valid(
    authenticator: Authenticator,
    test_user: User,
):
    """Test local password verification with valid credentials."""
    result = await authenticator.verify_password("testuser", "testpass123")

    assert result is True


@pytest.mark.asyncio
async def test_verify_password_local_invalid(
    authenticator: Authenticator,
    test_user: User,
):
    """Test local password verification with invalid credentials."""
    with pytest.raises(InvalidCredentialsError):
        await authenticator.verify_password("testuser", "wrongpass")


@pytest.mark.asyncio
async def test_verify_password_user_not_found(authenticator: Authenticator):
    """Test password verification for non-existent user."""
    with pytest.raises(UserNotFoundError) as exc_info:
        await authenticator.verify_password("nonexistent", "pass")

    assert "nonexistent" in str(exc_info.value)


@pytest.mark.asyncio
async def test_verify_password_disabled_user(
    authenticator: Authenticator,
    disabled_user: User,
):
    """Test password verification for disabled user."""
    with pytest.raises(UserDisabledError) as exc_info:
        await authenticator.verify_password("disabled", "pass123")

    assert "disabled" in str(exc_info.value)


# Session management tests

@pytest.mark.asyncio
async def test_create_session(
    authenticator: Authenticator,
    test_user: User,
):
    """Test session creation."""
    session_token = await authenticator.create_session(
        user_id=test_user.id,
        ip_address="192.168.1.100",
        user_agent="TestClient/1.0",
    )

    assert isinstance(session_token.token, str)
    assert session_token.user_id == test_user.id
    assert session_token.session_id > 0
    assert session_token.expires_at > datetime.now(timezone.utc)


@pytest.mark.asyncio
async def test_verify_session_valid(
    authenticator: Authenticator,
    test_user: User,
):
    """Test session verification with valid token."""
    session_token = await authenticator.create_session(test_user.id)

    user_id = await authenticator.verify_session(session_token.token)

    assert user_id == test_user.id


@pytest.mark.asyncio
async def test_verify_session_invalid_token(authenticator: Authenticator):
    """Test session verification with invalid token."""
    with pytest.raises(InvalidTokenError):
        await authenticator.verify_session("invalid.token.here")


@pytest.mark.asyncio
async def test_get_authenticated_user(
    authenticator: Authenticator,
    test_user: User,
):
    """Test getting authenticated user from token."""
    session_token = await authenticator.create_session(test_user.id)

    auth_user = await authenticator.get_authenticated_user(session_token.token)

    assert auth_user.user_id == test_user.id
    assert auth_user.username == "testuser"
    assert auth_user.role == "USER"
    assert auth_user.is_active is True


@pytest.mark.asyncio
async def test_logout(
    authenticator: Authenticator,
    test_user: User,
):
    """Test user logout (session deletion)."""
    session_token = await authenticator.create_session(test_user.id)

    # Logout
    result = await authenticator.logout(session_token.token)
    assert result is True

    # Verify session is deleted
    with pytest.raises((SessionNotFoundError, InvalidTokenError)):
        await authenticator.verify_session(session_token.token)


# External authentication tests

@pytest.mark.asyncio
async def test_external_auth_success(
    db_session: AsyncSession,
    test_user: User,
    secret_key: str,
):
    """Test external authentication success."""
    authenticator = Authenticator(
        db=db_session,
        secret_key=secret_key,
        external_auth_enabled=True,
        external_auth_url="http://sybase-api.example.com/auth",
        external_auth_timeout=2,
    )

    # Mock httpx client
    with patch("httpx.AsyncClient") as mock_client:
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"authenticated": True, "success": True}

        mock_client.return_value.__aenter__.return_value.post = AsyncMock(
            return_value=mock_response
        )

        result = await authenticator.verify_password("testuser", "testpass123")

        assert result is True


@pytest.mark.asyncio
async def test_external_auth_timeout(
    db_session: AsyncSession,
    test_user: User,
    secret_key: str,
):
    """Test external authentication timeout."""
    authenticator = Authenticator(
        db=db_session,
        secret_key=secret_key,
        external_auth_enabled=True,
        external_auth_url="http://sybase-api.example.com/auth",
        external_auth_timeout=2,
    )

    # Mock httpx timeout
    with patch("httpx.AsyncClient") as mock_client:
        mock_client.return_value.__aenter__.return_value.post = AsyncMock(
            side_effect=httpx.TimeoutException("Timeout")
        )

        with pytest.raises(ExternalAuthTimeoutError):
            await authenticator.verify_password("testuser", "testpass123")


# Convenience function tests

@pytest.mark.asyncio
async def test_verify_password_convenience(
    db_session: AsyncSession,
    test_user: User,
):
    """Test verify_password convenience function."""
    result = await verify_password("testuser", "testpass123", db_session)

    assert result is True


def test_hash_password_convenience():
    """Test hash_password convenience function."""
    hash1 = hash_password("test123")

    assert hash1.startswith("$argon2id$")
    assert _verify_password("test123", hash1) is True


@pytest.mark.asyncio
async def test_create_session_convenience(
    db_session: AsyncSession,
    test_user: User,
):
    """Test create_session convenience function."""
    session_token = await create_session(test_user.id, db_session)

    assert isinstance(session_token.token, str)
    assert session_token.user_id == test_user.id


@pytest.mark.asyncio
async def test_verify_session_convenience(
    db_session: AsyncSession,
    test_user: User,
):
    """Test verify_session convenience function."""
    session_token = await create_session(test_user.id, db_session)

    user_id = await verify_session(session_token.token, db_session)

    assert user_id == test_user.id


@pytest.mark.asyncio
async def test_verify_session_convenience_invalid(db_session: AsyncSession):
    """Test verify_session convenience function with invalid token."""
    user_id = await verify_session("invalid.token", db_session)

    assert user_id is None
