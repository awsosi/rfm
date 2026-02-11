"""
User preferences API routes.

Allows authenticated users to manage their UI preferences and settings.
"""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from api.middleware.auth import get_current_user
from api.schemas import UserPreferencesResponse, UserPreferencesUpdate
from database import get_db
from models import User, UserPreferences


router = APIRouter(prefix="/api/preferences", tags=["preferences"])


@router.get("/me", response_model=UserPreferencesResponse)
async def get_my_preferences(
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """Get current user's preferences."""
    stmt = select(UserPreferences).where(UserPreferences.user_id == current_user.id)
    result = await db.execute(stmt)
    preferences = result.scalar_one_or_none()

    # Create default preferences if not exists
    if not preferences:
        preferences = UserPreferences(user_id=current_user.id)
        db.add(preferences)
        await db.commit()
        await db.refresh(preferences)

    return UserPreferencesResponse.model_validate(preferences)


@router.put("/me", response_model=UserPreferencesResponse)
async def update_my_preferences(
    preferences_data: UserPreferencesUpdate,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """Update current user's preferences."""
    stmt = select(UserPreferences).where(UserPreferences.user_id == current_user.id)
    result = await db.execute(stmt)
    preferences = result.scalar_one_or_none()

    # Create if not exists
    if not preferences:
        preferences = UserPreferences(user_id=current_user.id)
        db.add(preferences)

    # Update fields
    update_data = preferences_data.model_dump(exclude_none=True)
    for field, value in update_data.items():
        setattr(preferences, field, value)

    await db.commit()
    await db.refresh(preferences)

    return UserPreferencesResponse.model_validate(preferences)


@router.delete("/me", response_model=UserPreferencesResponse)
async def reset_my_preferences(
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """Reset user preferences to defaults."""
    stmt = select(UserPreferences).where(UserPreferences.user_id == current_user.id)
    result = await db.execute(stmt)
    preferences = result.scalar_one_or_none()

    if preferences:
        # Reset to defaults
        preferences.remember_last_paths = True
        preferences.last_path_a = None
        preferences.last_path_b = None
        preferences.ui_theme = "system"
        preferences.ui_language = "auto"
        preferences.pane_layout = "horizontal"
        preferences.custom_settings = None
    else:
        # Create with defaults
        preferences = UserPreferences(user_id=current_user.id)
        db.add(preferences)

    await db.commit()
    await db.refresh(preferences)

    return UserPreferencesResponse.model_validate(preferences)
