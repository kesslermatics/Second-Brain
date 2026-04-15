"""User state routes — cross-device key-value persistence."""

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.database import get_db
from app.auth import get_current_user
from app.models import User, UserState

router = APIRouter(prefix="/state", tags=["state"])


@router.get("/{key}")
async def get_state(
    key: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Get a stored state value by key. Returns null value if not found."""
    result = await db.execute(
        select(UserState).where(
            UserState.user_id == current_user.id,
            UserState.key == key,
        )
    )
    state = result.scalar_one_or_none()
    if not state:
        return {"key": key, "value": None}
    return {"key": state.key, "value": state.value}


@router.put("/{key}")
async def put_state(
    key: str,
    data: dict,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Upsert a state value. Body: { "value": "..." } — value is stored as-is (string/JSON)."""
    value = data.get("value", "")
    if value is None:
        value = ""

    result = await db.execute(
        select(UserState).where(
            UserState.user_id == current_user.id,
            UserState.key == key,
        )
    )
    state = result.scalar_one_or_none()

    if state:
        state.value = str(value)
    else:
        state = UserState(
            user_id=current_user.id,
            key=key,
            value=str(value),
        )
        db.add(state)

    await db.flush()
    await db.refresh(state)
    await db.commit()
    return {"key": state.key, "value": state.value}


@router.delete("/{key}")
async def delete_state(
    key: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Delete a state value by key."""
    result = await db.execute(
        select(UserState).where(
            UserState.user_id == current_user.id,
            UserState.key == key,
        )
    )
    state = result.scalar_one_or_none()
    if state:
        await db.delete(state)
        await db.commit()
    return {"ok": True}
