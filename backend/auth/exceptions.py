"""
Custom exceptions for authentication module.

All authentication-related errors inherit from AuthenticationError base class.
"""


class AuthenticationError(Exception):
    """Base exception for all authentication errors."""

    def __init__(self, message: str = "Authentication failed"):
        self.message = message
        super().__init__(self.message)


class InvalidCredentialsError(AuthenticationError):
    """Raised when username or password is invalid."""

    def __init__(self, message: str = "Invalid username or password"):
        super().__init__(message)


class UserNotFoundError(AuthenticationError):
    """Raised when user does not exist in database."""

    def __init__(self, username: str):
        super().__init__(f"User '{username}' not found")
        self.username = username


class UserDisabledError(AuthenticationError):
    """Raised when user account is disabled."""

    def __init__(self, username: str):
        super().__init__(f"User account '{username}' is disabled")
        self.username = username


class InvalidTokenError(AuthenticationError):
    """Raised when JWT token is invalid or malformed."""

    def __init__(self, message: str = "Invalid authentication token"):
        super().__init__(message)


class ExpiredTokenError(AuthenticationError):
    """Raised when JWT token has expired."""

    def __init__(self, message: str = "Authentication token has expired"):
        super().__init__(message)


class SessionNotFoundError(AuthenticationError):
    """Raised when session does not exist in database."""

    def __init__(self, session_id: int):
        super().__init__(f"Session {session_id} not found")
        self.session_id = session_id


class ExternalAuthError(AuthenticationError):
    """Raised when external authentication API fails."""

    def __init__(self, message: str = "External authentication service unavailable"):
        super().__init__(message)


class ExternalAuthTimeoutError(ExternalAuthError):
    """Raised when external authentication API times out."""

    def __init__(self, timeout: int = 2):
        super().__init__(f"External authentication timed out after {timeout}s")
        self.timeout = timeout


class PasswordHashError(AuthenticationError):
    """Raised when password hashing fails."""

    def __init__(self, message: str = "Failed to hash password"):
        super().__init__(message)


class SessionCreationError(AuthenticationError):
    """Raised when session creation fails."""

    def __init__(self, message: str = "Failed to create session"):
        super().__init__(message)
