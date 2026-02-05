"""
Main authentication module for Modular File Manager.

Provides authentication against local database with optional PolkaSQL/Sybase API
integration. Includes admin emergency login via .env credentials.

Features:
- Local user database authentication
- Optional PolkaSQL/Sybase authentication (RFM_Auth API)
- Admin fallback authentication via .env
- JWT session management (30-day long-lived tokens)
- Argon2 password hashing
"""

import os
from datetime import datetime, timedelta, timezone
from typing import Optional

import httpx
from loguru import logger
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from auth.exceptions import (
    InvalidCredentialsError,
    UserNotFoundError,
    UserDisabledError,
    InvalidTokenError,
    ExpiredTokenError,
    SessionNotFoundError,
    ExternalAuthError,
    ExternalAuthTimeoutError,
    SessionCreationError,
)
from auth.models import (
    Credentials,
    AuthenticatedUser,
    SessionToken,
    TokenPayload,
    ExternalAuthRequest,
    ExternalAuthResponse,
)
from auth.utils import (
    hash_password as _hash_password,
    verify_password as _verify_password,
    check_needs_rehash,
    create_jwt_token,
    decode_jwt_token,
    get_secret_key,
)
from models import User, Session as SessionModel


class Authenticator:
    """
    Main authentication class handling all auth operations.

    Supports:
    - Local database authentication
    - External Sybase API authentication (optional)
    - Admin emergency login via .env
    - JWT session management
    """

    def __init__(
        self,
        db: AsyncSession,
        secret_key: Optional[str] = None,
        external_auth_enabled: bool = False,
        external_auth_url: Optional[str] = None,
        external_auth_timeout: int = 2,
    ):
        """
        Initialize authenticator.

        Args:
            db: Database session
            secret_key: Secret key for JWT (if None, loads from env)
            external_auth_enabled: Enable external Sybase auth
            external_auth_url: External auth API endpoint
            external_auth_timeout: External auth timeout in seconds
        """
        self.db = db
        self.secret_key = secret_key or get_secret_key()
        self.external_auth_enabled = external_auth_enabled
        self.external_auth_url = external_auth_url
        self.external_auth_timeout = external_auth_timeout

        # Load admin credentials from .env
        self.admin_username = os.getenv("ADMIN_USERNAME", "admin")
        self.admin_password_hash = os.getenv(
            "ADMIN_PASSWORD_HASH",
            # Default hash for "admin123"
            "$argon2id$v=19$m=65536,t=3,p=4$kxMCoNQ6p1QqxTiHUGqNUQ$+yGg0YZMk3gqGZb5ZZWqJqHZ5C8xLBzN5sZq4gZQwWk",
        )

    async def verify_password(self, username: str, password: str) -> bool:
        """
        Verify username and password against database or external API.

        Flow:
        1. Check admin emergency login (.env)
        2. Lookup user in database
        3. If external auth enabled, verify with Sybase API (2s timeout)
        4. Fallback to local password verification
        5. Rehash if parameters changed

        Args:
            username: Username to verify
            password: Plain text password

        Returns:
            True if credentials are valid, False otherwise

        Raises:
            UserNotFoundError: If user doesn't exist
            UserDisabledError: If user account is disabled

        Example:
            >>> auth = Authenticator(db)
            >>> await auth.verify_password("admin", "admin123")
            True
            >>> await auth.verify_password("admin", "wrongpass")
            False
        """
        # Admin emergency login (always functional)
        if username == self.admin_username:
            if _verify_password(password, self.admin_password_hash):
                logger.info(f"Admin emergency login successful: {username}")
                return True
            else:
                logger.warning(f"Admin emergency login failed: {username}")
                raise InvalidCredentialsError()

        # Lookup user in database
        stmt = select(User).where(User.username == username)
        result = await self.db.execute(stmt)
        user = result.scalar_one_or_none()

        if not user:
            logger.warning(f"User not found: {username}")
            raise UserNotFoundError(username)

        if not user.is_active:
            logger.warning(f"User disabled: {username}")
            raise UserDisabledError(username)

        # External authentication (if enabled)
        if self.external_auth_enabled:
            try:
                external_valid = await self._verify_external_auth(username, password)

                if external_valid:
                    logger.info(f"External auth successful: {username}")
                    return True
                else:
                    # External auth failed - DENY (don't fallback)
                    logger.warning(f"External auth failed: {username}")
                    raise InvalidCredentialsError("External authentication failed")

            except ExternalAuthTimeoutError:
                # Timeout - DENY (don't fallback)
                logger.error(f"External auth timeout: {username}")
                raise ExternalAuthError("External authentication service timeout")

            except ExternalAuthError as exc:
                # External auth error - DENY (don't fallback)
                logger.error(f"External auth error: {username} - {exc}")
                raise

        # Local password verification
        if _verify_password(password, user.password_hash):
            logger.info(f"Local auth successful: {username}")

            # Check if password needs rehashing
            if check_needs_rehash(user.password_hash):
                user.password_hash = _hash_password(password)
                await self.db.commit()
                logger.info(f"Password rehashed for user: {username}")

            return True
        else:
            logger.warning(f"Local auth failed: {username}")
            raise InvalidCredentialsError()

    async def _verify_external_auth(
        self,
        username: str,
        password: str,
    ) -> bool:
        """
        Verify credentials against external Sybase API.

        Args:
            username: Username to verify
            password: Password to verify

        Returns:
            True if external auth successful, False otherwise

        Raises:
            ExternalAuthTimeoutError: If request times out
            ExternalAuthError: If external API fails
        """
        if not self.external_auth_url:
            raise ExternalAuthError("External auth URL not configured")

        try:
            # Prepare request
            auth_request = ExternalAuthRequest(
                username=username,
                password=password,
                stored_proc=os.getenv("SYBASE_AUTH_STORED_PROC"),
            )

            # Make async HTTP request with timeout
            async with httpx.AsyncClient(timeout=self.external_auth_timeout) as client:
                response = await client.post(
                    self.external_auth_url,
                    json=auth_request.model_dump(),
                )

                if response.status_code == 200:
                    auth_response = ExternalAuthResponse(**response.json())
                    return auth_response.authenticated or auth_response.success
                else:
                    logger.error(
                        f"External auth HTTP {response.status_code}: {response.text}"
                    )
                    return False

        except httpx.TimeoutException:
            raise ExternalAuthTimeoutError(self.external_auth_timeout)

        except httpx.HTTPError as exc:
            raise ExternalAuthError(f"External auth HTTP error: {exc}")

        except Exception as exc:
            raise ExternalAuthError(f"External auth failed: {exc}")

    def hash_password(self, password: str) -> str:
        """
        Hash password using Argon2id.

        Args:
            password: Plain text password to hash

        Returns:
            Argon2 hash string

        Example:
            >>> auth = Authenticator(db)
            >>> hash = auth.hash_password("admin123")
            >>> hash.startswith("$argon2id$")
            True
        """
        return _hash_password(password)

    async def create_session(
        self,
        user_id: int,
        ip_address: Optional[str] = None,
        user_agent: Optional[str] = None,
        expires_in_days: int = 30,
    ) -> SessionToken:
        """
        Create new session and generate JWT token.

        Args:
            user_id: User ID to create session for
            ip_address: Client IP address
            user_agent: Client user agent
            expires_in_days: Token lifetime in days

        Returns:
            SessionToken with token and metadata

        Raises:
            UserNotFoundError: If user doesn't exist
            SessionCreationError: If session creation fails

        Example:
            >>> auth = Authenticator(db)
            >>> session = await auth.create_session(user_id=1)
            >>> isinstance(session.token, str)
            True
        """
        try:
            # Get user from database
            stmt = select(User).where(User.id == user_id)
            result = await self.db.execute(stmt)
            user = result.scalar_one_or_none()

            if not user:
                raise UserNotFoundError(f"user_id={user_id}")

            # Calculate expiration
            expires_at = datetime.now(timezone.utc) + timedelta(days=expires_in_days)

            # Create session record
            session = SessionModel(
                user_id=user_id,
                token="",  # Will be set after JWT generation
                expires_at=expires_at,
                ip_address=ip_address,
                user_agent=user_agent,
            )

            self.db.add(session)
            await self.db.flush()

            # Generate JWT token
            token_payload = {
                "user_id": user.id,
                "username": user.username,
                "role": user.role.value,
                "session_id": session.id,
            }

            token = create_jwt_token(
                token_payload,
                self.secret_key,
                expires_in_days=expires_in_days,
            )

            # Update session with token
            session.token = token
            await self.db.commit()
            await self.db.refresh(session)

            logger.info(f"Session created: user_id={user_id}, session_id={session.id}")

            return SessionToken(
                token=token,
                user_id=user_id,
                session_id=session.id,
                expires_at=expires_at,
            )

        except UserNotFoundError:
            raise

        except Exception as exc:
            await self.db.rollback()
            raise SessionCreationError(f"Failed to create session: {exc}")

    async def verify_session(self, token: str) -> Optional[int]:
        """
        Verify JWT token and return user_id if valid.

        Checks both JWT validity and database session existence.

        Args:
            token: JWT token string

        Returns:
            User ID if session is valid, None otherwise

        Raises:
            InvalidTokenError: If token is malformed
            ExpiredTokenError: If token has expired
            SessionNotFoundError: If session not in database

        Example:
            >>> auth = Authenticator(db)
            >>> session = await auth.create_session(user_id=1)
            >>> user_id = await auth.verify_session(session.token)
            >>> user_id
            1
        """
        try:
            # Decode JWT token
            payload = decode_jwt_token(token, self.secret_key)

            user_id = payload.get("user_id")
            session_id = payload.get("session_id")

            if not user_id or not session_id:
                raise InvalidTokenError("Token missing required fields")

            # Verify session exists in database
            stmt = select(SessionModel).where(SessionModel.id == session_id)
            result = await self.db.execute(stmt)
            session = result.scalar_one_or_none()

            if not session:
                raise SessionNotFoundError(session_id)

            if session.user_id != user_id:
                raise InvalidTokenError("Session user mismatch")

            if session.is_expired:
                raise ExpiredTokenError("Session has expired")

            if session.token != token:
                raise InvalidTokenError("Token mismatch")

            return user_id

        except (InvalidTokenError, ExpiredTokenError, SessionNotFoundError):
            raise

        except Exception as exc:
            raise InvalidTokenError(f"Session verification failed: {exc}")

    async def get_authenticated_user(self, token: str) -> AuthenticatedUser:
        """
        Get authenticated user from token.

        Args:
            token: JWT token string

        Returns:
            AuthenticatedUser with user details

        Raises:
            InvalidTokenError: If token is invalid
            UserNotFoundError: If user doesn't exist
        """
        user_id = await self.verify_session(token)

        if not user_id:
            raise InvalidTokenError("Invalid session")

        stmt = select(User).where(User.id == user_id)
        result = await self.db.execute(stmt)
        user = result.scalar_one_or_none()

        if not user:
            raise UserNotFoundError(f"user_id={user_id}")

        return AuthenticatedUser(
            user_id=user.id,
            username=user.username,
            role=user.role.value,
            is_active=user.is_active,
        )

    async def logout(self, token: str) -> bool:
        """
        Logout user by deleting session.

        Args:
            token: JWT token string

        Returns:
            True if logout successful
        """
        try:
            payload = decode_jwt_token(token, self.secret_key)
            session_id = payload.get("session_id")

            if session_id:
                stmt = select(SessionModel).where(SessionModel.id == session_id)
                result = await self.db.execute(stmt)
                session = result.scalar_one_or_none()

                if session:
                    await self.db.delete(session)
                    await self.db.commit()
                    logger.info(f"Session deleted: session_id={session_id}")
                    return True

            return False

        except Exception as exc:
            logger.error(f"Logout failed: {exc}")
            return False


# Convenience functions for direct usage

async def verify_password(
    username: str,
    password: str,
    db: AsyncSession,
    **kwargs,
) -> bool:
    """
    Convenience function to verify password.

    Args:
        username: Username to verify
        password: Password to verify
        db: Database session
        **kwargs: Additional arguments for Authenticator

    Returns:
        True if credentials valid, False otherwise
    """
    auth = Authenticator(db, **kwargs)
    try:
        return await auth.verify_password(username, password)
    except (InvalidCredentialsError, UserNotFoundError, UserDisabledError):
        return False


def hash_password(password: str) -> str:
    """
    Convenience function to hash password.

    Args:
        password: Plain text password

    Returns:
        Argon2 hash string
    """
    return _hash_password(password)


async def create_session(
    user_id: int,
    db: AsyncSession,
    **kwargs,
) -> SessionToken:
    """
    Convenience function to create session.

    Args:
        user_id: User ID
        db: Database session
        **kwargs: Additional arguments for Authenticator

    Returns:
        SessionToken
    """
    auth = Authenticator(db, **kwargs)
    return await auth.create_session(user_id, **kwargs)


async def verify_session(
    token: str,
    db: AsyncSession,
    **kwargs,
) -> Optional[int]:
    """
    Convenience function to verify session.

    Args:
        token: JWT token
        db: Database session
        **kwargs: Additional arguments for Authenticator

    Returns:
        User ID if valid, None otherwise
    """
    auth = Authenticator(db, **kwargs)
    try:
        return await auth.verify_session(token)
    except (InvalidTokenError, ExpiredTokenError, SessionNotFoundError):
        return None
