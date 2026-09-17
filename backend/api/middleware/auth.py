"""
Authentication middleware for JWT token verification.

Validates session tokens from database and attaches user information
to request state for use in route handlers.
"""

from datetime import datetime, timedelta, timezone
from typing import Annotated, Optional

import jwt
from fastapi import Depends, HTTPException, status, Request
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from api.config import get_settings, Settings
from api.schemas import TokenData
from database import get_db
from models import Config, Session as SessionModel, User, UserRole


security = HTTPBearer()


class AuthenticationError(HTTPException):
    """Custom authentication error exception."""

    def __init__(self, detail: str = "Could not validate credentials"):
        super().__init__(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=detail,
            headers={"WWW-Authenticate": "Bearer"},
        )


class PermissionDeniedError(HTTPException):
    """Custom permission denied exception."""

    def __init__(self, detail: str = "Permission denied"):
        super().__init__(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=detail,
        )


async def verify_token(
    token: str,
    settings: Settings,
) -> TokenData:
    """
    Verify JWT token and extract payload.

    Args:
        token: JWT token string
        settings: Application settings

    Returns:
        TokenData with user information

    Raises:
        AuthenticationError: If token is invalid or expired
    """
    try:
        payload = jwt.decode(
            token,
            settings.secret_key,
            algorithms=[settings.algorithm],
        )

        user_id: int = payload.get("user_id")
        username: str = payload.get("username")
        role: str = payload.get("role")
        session_id: int = payload.get("session_id")

        if user_id is None or username is None or role is None or session_id is None:
            raise AuthenticationError("Invalid token payload")

        return TokenData(
            user_id=user_id,
            username=username,
            role=UserRole(role),
            session_id=session_id,
        )

    except jwt.ExpiredSignatureError:
        raise AuthenticationError("Token has expired")
    except jwt.InvalidTokenError:
        raise AuthenticationError("Invalid token")
    except ValueError:
        raise AuthenticationError("Invalid token data")


async def verify_session(
    token_data: TokenData,
    db: AsyncSession,
) -> SessionModel:
    """
    Verify session exists in database and is not expired.

    Args:
        token_data: Decoded token data
        db: Database session

    Returns:
        Session model from database

    Raises:
        AuthenticationError: If session is invalid or expired
    """
    stmt = select(SessionModel).where(SessionModel.id == token_data.session_id)
    result = await db.execute(stmt)
    session = result.scalar_one_or_none()

    if not session:
        raise AuthenticationError("Session not found")

    if session.user_id != token_data.user_id:
        raise AuthenticationError("Session user mismatch")

    if session.is_expired:
        raise AuthenticationError("Session has expired")

    return session


async def get_current_user(
    credentials: Annotated[HTTPAuthorizationCredentials, Depends(security)],
    db: Annotated[AsyncSession, Depends(get_db)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> User:
    """
    Get current authenticated user from JWT token.

    Dependency for route handlers that require authentication.

    Args:
        credentials: HTTP Bearer token
        db: Database session
        settings: Application settings

    Returns:
        Authenticated User model

    Raises:
        AuthenticationError: If authentication fails
    """
    token = credentials.credentials

    # Verify token and extract payload
    token_data = await verify_token(token, settings)

    # Verify session in database
    session = await verify_session(token_data, db)

    # Get user from database
    stmt = select(User).where(User.id == token_data.user_id)
    result = await db.execute(stmt)
    user = result.scalar_one_or_none()

    if not user:
        raise AuthenticationError("User not found")

    if not user.is_active:
        raise AuthenticationError("User account is disabled")

    # Attach session info to user for later use
    user._current_session = session

    return user


async def get_current_active_user(
    current_user: Annotated[User, Depends(get_current_user)],
) -> User:
    """
    Get current active user (convenience wrapper).

    Args:
        current_user: Current authenticated user

    Returns:
        Active user
    """
    return current_user


def require_role(required_role: UserRole):
    """
    Dependency factory for role-based access control.

    Usage:
        @router.get("/admin", dependencies=[Depends(require_role(UserRole.ADMIN))])
        async def admin_endpoint():
            pass

    Args:
        required_role: Minimum required role

    Returns:
        Dependency function that checks user role
    """

    async def check_role(
        current_user: Annotated[User, Depends(get_current_user)],
    ) -> User:
        """Check if user has required role."""
        # Role hierarchy: admin > user
        role_levels = {
            UserRole.USER: 0,
            UserRole.ADMIN: 1,
        }

        user_level = role_levels.get(current_user.role, 0)
        required_level = role_levels.get(required_role, 999)

        if user_level < required_level:
            raise PermissionDeniedError(
                f"This endpoint requires {required_role.value} role or higher"
            )

        return current_user

    return check_role


# Convenience dependencies for common roles
require_admin = require_role(UserRole.ADMIN)
require_user = require_role(UserRole.USER)


# =============================================================================
# Session policy (Admin Panel: Session & User Management)
# =============================================================================

# Config key -> (default, minimum)
SESSION_POLICY_DEFAULTS = {
    "session_lifetime_days": (5, 1),
    "session_remember_me_days": (30, 1),
    "admin_reauth_minutes": (15, 1),
}


async def get_session_policy(db: AsyncSession) -> dict:
    """Session policy from the config table, falling back to the defaults."""
    result = await db.execute(
        select(Config.key, Config.value).where(Config.key.in_(SESSION_POLICY_DEFAULTS))
    )
    stored = {row.key: row.value for row in result}
    policy = {}
    for key, (default, minimum) in SESSION_POLICY_DEFAULTS.items():
        try:
            policy[key] = max(int(stored.get(key, default)), minimum)
        except (TypeError, ValueError):
            policy[key] = default
    return policy


def session_expiry(policy: dict, user: User, remember_me: bool) -> tuple[datetime, bool]:
    """
    Expiry of a session opened (or refreshed) now, and whether it is remembered.

    "Remember me" never applies to admins: their sessions always use the
    standard lifetime.
    """
    remember = bool(remember_me) and user.role != UserRole.ADMIN
    days = policy["session_remember_me_days" if remember else "session_lifetime_days"]
    return datetime.now(timezone.utc) + timedelta(days=days), remember


class ReauthenticationRequired(HTTPException):
    """The admin must confirm their password before changing system settings."""

    def __init__(self):
        super().__init__(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "code": "reauth_required",
                "message": "Confirm your password to change system settings",
            },
        )


async def require_recent_auth(
    current_user: Annotated[User, Depends(require_admin)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> User:
    """
    Admin whose password was typed in this session within ``admin_reauth_minutes``.

    Guards changes to system settings. The client answers 403
    ``reauth_required`` with POST /api/auth/reauthenticate and retries.
    """
    session = getattr(current_user, "_current_session", None)
    confirmed_at = session.reauthenticated_at if session else None
    if confirmed_at is None:
        raise ReauthenticationRequired()
    policy = await get_session_policy(db)
    if datetime.now(timezone.utc) - confirmed_at > timedelta(minutes=policy["admin_reauth_minutes"]):
        raise ReauthenticationRequired()
    return current_user


async def get_optional_user(
    request: Request,
    db: Annotated[AsyncSession, Depends(get_db)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> Optional[User]:
    """
    Get current user if authenticated, None otherwise.

    Useful for endpoints that work for both authenticated and anonymous users.

    Args:
        request: FastAPI request
        db: Database session
        settings: Application settings

    Returns:
        User if authenticated, None otherwise
    """
    auth_header = request.headers.get("Authorization")

    if not auth_header or not auth_header.startswith("Bearer "):
        return None

    token = auth_header.replace("Bearer ", "")

    try:
        token_data = await verify_token(token, settings)
        session = await verify_session(token_data, db)

        stmt = select(User).where(User.id == token_data.user_id)
        result = await db.execute(stmt)
        user = result.scalar_one_or_none()

        if user and user.is_active:
            user._current_session = session
            return user

    except (AuthenticationError, Exception):
        pass

    return None


def get_user_from_request(request: Request) -> Optional[User]:
    """
    Get user from request state (set by middleware).

    Args:
        request: FastAPI request

    Returns:
        User if authenticated, None otherwise
    """
    return getattr(request.state, "user", None)


def get_session_from_user(user: User) -> Optional[SessionModel]:
    """
    Get session from user object (attached by get_current_user).

    Args:
        user: User model

    Returns:
        Session model if available
    """
    return getattr(user, "_current_session", None)
