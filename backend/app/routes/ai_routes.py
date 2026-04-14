from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from uuid import UUID
from app.database import get_db
from app.auth import get_current_user
from app.models import User, Note
from app.schemas import AIEditRequest, AIEditResponse
from app.services.ai_service import edit_note_with_ai

router = APIRouter(prefix="/ai", tags=["ai"])


@router.post("/edit-note", response_model=AIEditResponse)
async def ai_edit_note(
    request: AIEditRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    note = await db.get(Note, request.note_id)
    if not note or note.user_id != current_user.id:
        raise HTTPException(status_code=404, detail="Note not found")

    suggested_content = await edit_note_with_ai(note.content, request.instruction)

    return AIEditResponse(
        original_content=note.content,
        suggested_content=suggested_content,
    )
