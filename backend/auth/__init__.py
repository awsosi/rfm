"""
Authentication module for Modular File Manager.

Provides secure authentication with local database and optional external API integration.

Main components:
- Authenticator: Main authentication class
- hash_password: Argon2 password hashing
- verify_password: Password verification
- create_session: JWT session creation
- verify_session: JWT session verification

Usage:
    from auth import Authenticator, hash_password, verify_password

    # Hash password
    password_hash = hash_password("admin123")

    # Verify credentials
    auth = Authenticator(db_session)
    is_valid = await auth.verify_password("admin", "admin123")

    # Create session
    session_token = await auth.create_session(user_id=1)

    # Verify session
    user_id = await auth.verify_session(session_token.token)
"""

from auth.authenticator import (
    Authenticator,
    verify_password,
    hash_password,
    create_session,
    verify_session,
)
from auth.exceptions import (
    AuthenticationError,
    InvalidCredentialsError,
    UserNotFoundError,
    UserDisabledError,
    InvalidTokenError,
    ExpiredTokenError,
    SessionNotFoundError,
    ExternalAuthError,
    ExternalAuthTimeoutError,
    PasswordHashError,
    SessionCreationError,
)
from auth.models import (
    Credentials,
    AuthenticatedUser,
    SessionToken,
    TokenPayload,
    ExternalAuthRequest,
    ExternalAuthResponse,
    PasswordHashResult,
    SessionInfo,
)
from auth.utils import (
    create_jwt_token,
    decode_jwt_token,
    get_secret_key,
    generate_secret_key,
    validate_password_strength,
)

__version__ = "1.0.0"

__all__ = [
    # Main authenticator
    "Authenticator",
    # Convenience functions
    "verify_password",
    "hash_password",
    "create_session",
    "verify_session",
    # Exceptions
    "AuthenticationError",
    "InvalidCredentialsError",
    "UserNotFoundError",
    "UserDisabledError",
    "InvalidTokenError",
    "ExpiredTokenError",
    "SessionNotFoundError",
    "ExternalAuthError",
    "ExternalAuthTimeoutError",
    "PasswordHashError",
    "SessionCreationError",
    # Models
    "Credentials",
    "AuthenticatedUser",
    "SessionToken",
    "TokenPayload",
    "ExternalAuthRequest",
    "ExternalAuthResponse",
    "PasswordHashResult",
    "SessionInfo",
    # Utils
    "create_jwt_token",
    "decode_jwt_token",
    "get_secret_key",
    "generate_secret_key",
    "validate_password_strength",
]
