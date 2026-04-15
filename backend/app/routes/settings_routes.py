from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.database import get_db
from app.auth import get_current_user
from app.models import User, UserSettings
from app.schemas import SettingsUpdate, SettingsResponse
from app.services.ai_service import get_default_prompts

router = APIRouter(prefix="/settings", tags=["settings"])


@router.get("", response_model=SettingsResponse)
async def get_settings(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Get user's prompt settings. Returns custom prompts (if set) and defaults."""
    result = await db.execute(
        select(UserSettings).where(UserSettings.user_id == current_user.id)
    )
    user_settings = result.scalar_one_or_none()

    defaults = get_default_prompts()

    return SettingsResponse(
        note_prompt=user_settings.note_prompt if user_settings else None,
        qa_prompt=user_settings.qa_prompt if user_settings else None,
        edit_prompt=user_settings.edit_prompt if user_settings else None,
        note_prompt_default=defaults["note_prompt"],
        qa_prompt_default=defaults["qa_prompt"],
        edit_prompt_default=defaults["edit_prompt"],
    )


@router.put("", response_model=SettingsResponse)
async def update_settings(
    data: SettingsUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Update user's custom prompt settings."""
    result = await db.execute(
        select(UserSettings).where(UserSettings.user_id == current_user.id)
    )
    user_settings = result.scalar_one_or_none()

    if not user_settings:
        user_settings = UserSettings(user_id=current_user.id)
        db.add(user_settings)

    if data.note_prompt is not None:
        user_settings.note_prompt = data.note_prompt or None
    if data.qa_prompt is not None:
        user_settings.qa_prompt = data.qa_prompt or None
    if data.edit_prompt is not None:
        user_settings.edit_prompt = data.edit_prompt or None

    await db.flush()
    await db.refresh(user_settings)

    defaults = get_default_prompts()

    await db.commit()
    return SettingsResponse(
        note_prompt=user_settings.note_prompt,
        qa_prompt=user_settings.qa_prompt,
        edit_prompt=user_settings.edit_prompt,
        note_prompt_default=defaults["note_prompt"],
        qa_prompt_default=defaults["qa_prompt"],
        edit_prompt_default=defaults["edit_prompt"],
    )


@router.post("/reset", response_model=SettingsResponse)
async def reset_settings(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Reset all custom prompts to defaults."""
    result = await db.execute(
        select(UserSettings).where(UserSettings.user_id == current_user.id)
    )
    user_settings = result.scalar_one_or_none()

    if user_settings:
        user_settings.note_prompt = None
        user_settings.qa_prompt = None
        user_settings.edit_prompt = None
        await db.flush()
        await db.refresh(user_settings)

    defaults = get_default_prompts()

    await db.commit()
    return SettingsResponse(
        note_prompt=None,
        qa_prompt=None,
        edit_prompt=None,
        note_prompt_default=defaults["note_prompt"],
        qa_prompt_default=defaults["qa_prompt"],
        edit_prompt_default=defaults["edit_prompt"],
    )
