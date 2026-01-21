"""
Pydantic models for authentication module.

These are lightweight DTOs for auth operations, separate from database ORM models.
"""

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field, ConfigDict


class Credentials(BaseModel):
    """User credentials for authentication."""

    username: str = Field(..., min_length=1, max_length=100)
    password: str = Field(..., min_length=1)


class AuthenticatedUser(BaseModel):
    """Authenticated user information."""

    user_id: int
    username: str
    role: str
    is_active: bool = True


class SessionToken(BaseModel):
    """Session token with metadata."""

    token: str
    user_id: int
    session_id: int
    expires_at: datetime

    model_config = ConfigDict(from_attributes=True)


class TokenPayload(BaseModel):
    """JWT token payload."""

    user_id: int
    username: str
    role: str
    session_id: int
    iat: Optional[datetime] = None  # Issued at
    exp: Optional[datetime] = None  # Expiration


class ExternalAuthRequest(BaseModel):
    """Request to external authentication API."""

    username: str
    password: str
    stored_proc: Optional[str] = None


class ExternalAuthResponse(BaseModel):
    """Response from external authentication API."""

    success: bool
    message: Optional[str] = None
    authenticated: bool = False
    user_data: Optional[dict] = None


class PasswordHashResult(BaseModel):
    """Result of password hashing operation."""

    hash: str
    algorithm: str = "argon2id"
    needs_rehash: bool = False


class SessionInfo(BaseModel):
    """Session information."""

    session_id: int
    user_id: int
    token: str
    expires_at: datetime
    ip_address: Optional[str] = None
    user_agent: Optional[str] = None
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)
