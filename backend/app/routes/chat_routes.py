from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from typing import List
from uuid import UUID
from datetime import datetime, timezone
from app.database import get_db
from app.auth import get_current_user
from app.models import User, ChatSession, ChatMessage
from app.schemas import (
    ChatSessionCreate, ChatSessionResponse, ChatSessionDetailResponse,
    ChatMessageResponse, ChatMessageUpdate,
)

router = APIRouter(prefix="/chat", tags=["chat"])


@router.get("/sessions", response_model=List[ChatSessionResponse])
async def list_sessions(
    session_type: str = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    query = select(ChatSession).where(ChatSession.user_id == current_user.id)
    if session_type:
        query = query.where(ChatSession.session_type == session_type)
    query = query.order_by(ChatSession.updated_at.desc())
    result = await db.execute(query)
    return result.scalars().all()


@router.post("/sessions", response_model=ChatSessionResponse, status_code=status.HTTP_201_CREATED)
async def create_session(
    session: ChatSessionCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if session.session_type not in ("notes", "qa", "agent"):
        raise HTTPException(status_code=400, detail="session_type must be 'notes', 'qa', or 'agent'")

    new_session = ChatSession(
        title=session.title or "New Chat",
        session_type=session.session_type,
        user_id=current_user.id,
    )
    db.add(new_session)
    await db.flush()
    await db.refresh(new_session)
    await db.commit()
    return new_session


@router.get("/sessions/{session_id}", response_model=ChatSessionDetailResponse)
async def get_session(
    session_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    session = await db.get(ChatSession, session_id)
    if not session or session.user_id != current_user.id:
        raise HTTPException(status_code=404, detail="Session not found")

    messages_result = await db.execute(
        select(ChatMessage)
        .where(ChatMessage.session_id == session_id)
        .order_by(ChatMessage.created_at)
    )
    messages = messages_result.scalars().all()

    return ChatSessionDetailResponse(
        id=session.id,
        title=session.title,
        session_type=session.session_type,
        messages=[
            ChatMessageResponse(
                id=m.id,
                session_id=m.session_id,
                role=m.role,
                content=m.content,
                created_at=m.created_at,
            )
            for m in messages
        ],
        created_at=session.created_at,
        updated_at=session.updated_at,
    )


@router.delete("/sessions/{session_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_session(
    session_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    session = await db.get(ChatSession, session_id)
    if not session or session.user_id != current_user.id:
        raise HTTPException(status_code=404, detail="Session not found")
    await db.delete(session)
    await db.commit()


@router.put("/sessions/{session_id}", response_model=ChatSessionResponse)
async def update_session(
    session_id: UUID,
    data: dict,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    session = await db.get(ChatSession, session_id)
    if not session or session.user_id != current_user.id:
        raise HTTPException(status_code=404, detail="Session not found")
    if "title" in data:
        session.title = data["title"]
    await db.flush()
    await db.refresh(session)
    await db.commit()
    return session



@router.patch("/sessions/{session_id}/messages/{message_id}", response_model=ChatSessionDetailResponse)
async def edit_message_and_truncate_history(
    session_id: UUID,
    message_id: UUID,
    data: ChatMessageUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Edit a user prompt and remove the invalid conversation branch after it.

    Assistant messages (and later user turns) were generated from the old prompt,
    so keeping them would make the stored history inconsistent.
    """
    content = data.content.strip()
    if not content:
        raise HTTPException(status_code=422, detail="Message content must not be empty")

    session = await db.get(ChatSession, session_id)
    if not session or session.user_id != current_user.id:
        raise HTTPException(status_code=404, detail="Session not found")

    result = await db.execute(
        select(ChatMessage)
        .where(ChatMessage.session_id == session_id)
        .order_by(ChatMessage.created_at, ChatMessage.id)
    )
    messages = result.scalars().all()
    message_index = next((i for i, message in enumerate(messages) if message.id == message_id), None)
    if message_index is None or messages[message_index].role != "user":
        raise HTTPException(status_code=404, detail="User message not found")

    # Stop a possible run for this exact prompt before mutating its context.
    from app.services.job_store import job_store
    job_store.cancel_for_message(str(session_id), str(message_id))

    message = messages[message_index]
    message.content = content
    for stale_message in messages[message_index + 1:]:
        await db.delete(stale_message)

    session.updated_at = datetime.now(timezone.utc)
    await db.commit()
    return await get_session(session_id, db, current_user)
