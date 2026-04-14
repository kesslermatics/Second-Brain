from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
from typing import List
from uuid import UUID
from app.database import get_db
from app.auth import get_current_user
from app.models import User, Note, NoteVersion
from app.schemas import NoteVersionResponse

router = APIRouter(prefix="/notes", tags=["versions"])


@router.get("/{note_id}/versions", response_model=List[NoteVersionResponse])
async def list_versions(
    note_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    note = await db.get(Note, note_id)
    if not note or note.user_id != current_user.id:
        raise HTTPException(status_code=404, detail="Note not found")

    result = await db.execute(
        select(NoteVersion)
        .where(NoteVersion.note_id == note_id)
        .order_by(NoteVersion.version_number.desc())
    )
    return result.scalars().all()


@router.get("/{note_id}/versions/{version_id}", response_model=NoteVersionResponse)
async def get_version(
    note_id: UUID,
    version_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    note = await db.get(Note, note_id)
    if not note or note.user_id != current_user.id:
        raise HTTPException(status_code=404, detail="Note not found")

    version = await db.get(NoteVersion, version_id)
    if not version or version.note_id != note_id:
        raise HTTPException(status_code=404, detail="Version not found")

    return version


@router.post("/{note_id}/versions/{version_id}/restore", response_model=NoteVersionResponse)
async def restore_version(
    note_id: UUID,
    version_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Restore a note to a previous version (creates a new version of the current state first)."""
    note = await db.get(Note, note_id)
    if not note or note.user_id != current_user.id:
        raise HTTPException(status_code=404, detail="Note not found")

    version = await db.get(NoteVersion, version_id)
    if not version or version.note_id != note_id:
        raise HTTPException(status_code=404, detail="Version not found")

    # Get next version number
    max_ver_result = await db.execute(
        select(func.coalesce(func.max(NoteVersion.version_number), 0))
        .where(NoteVersion.note_id == note_id)
    )
    next_version = max_ver_result.scalar() + 1

    # Save current state as a new version before restoring
    current_snapshot = NoteVersion(
        note_id=note_id,
        title=note.title,
        content=note.content,
        version_number=next_version,
    )
    db.add(current_snapshot)

    # Restore
    note.title = version.title
    note.content = version.content
    await db.flush()
    await db.refresh(current_snapshot)

    return current_snapshot
