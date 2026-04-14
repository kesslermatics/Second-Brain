from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.database import get_db
from app.auth import get_current_user
from app.models import User, Note, Folder, Tag, note_tags
from app.schemas import SummaryRequest, SummaryResponse
from app.services.ai_service import generate_summary

router = APIRouter(prefix="/summary", tags=["summary"])


@router.post("", response_model=SummaryResponse)
async def create_summary(
    data: SummaryRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Generate an AI summary across notes (by folder, tag, or all)."""
    uid = current_user.id

    if data.scope == "folder" and data.folder_id:
        folder = await db.get(Folder, data.folder_id)
        if not folder or folder.user_id != uid:
            raise HTTPException(status_code=404, detail="Folder not found")

        # Get notes in folder and subfolders
        notes_result = await db.execute(
            select(Note)
            .join(Folder, Note.folder_id == Folder.id)
            .where(Note.user_id == uid, Folder.path.like(f"{folder.path}%"))
            .order_by(Note.updated_at.desc())
            .limit(30)
        )
        notes = notes_result.scalars().all()
        scope_label = f"Ordner: {folder.path}"

    elif data.scope == "tag" and data.tag_name:
        notes_result = await db.execute(
            select(Note)
            .join(note_tags, Note.id == note_tags.c.note_id)
            .join(Tag, Tag.id == note_tags.c.tag_id)
            .where(Tag.user_id == uid, Tag.name_lower == data.tag_name.lower())
            .order_by(Note.updated_at.desc())
            .limit(30)
        )
        notes = notes_result.scalars().all()
        scope_label = f"Tag: {data.tag_name}"

    elif data.scope == "all":
        notes_result = await db.execute(
            select(Note)
            .where(Note.user_id == uid)
            .order_by(Note.updated_at.desc())
            .limit(30)
        )
        notes = notes_result.scalars().all()
        scope_label = "Gesamtes Second Brain"

    else:
        raise HTTPException(status_code=400, detail="Invalid scope or missing parameters")

    if not notes:
        return SummaryResponse(summary="Keine Notizen gefunden.", source_count=0, scope=scope_label)

    notes_data = [{"title": n.title, "content": n.content} for n in notes]
    summary = await generate_summary(notes_data, scope_label)

    return SummaryResponse(
        summary=summary,
        source_count=len(notes),
        scope=scope_label,
    )
