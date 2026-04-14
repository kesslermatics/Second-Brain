from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from typing import List
from uuid import UUID
from app.database import get_db
from app.auth import get_current_user
from app.models import User, ChatSession, ChatMessage, Note, Folder
from app.schemas import (
    ChatSessionCreate, ChatSessionResponse, ChatSessionDetailResponse,
    ChatMessageCreate, ChatMessageResponse,
)
from app.services.ai_service import process_note_input, answer_with_rag
from app.services.vector_service import search_similar_notes

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
    if session.session_type not in ("notes", "qa"):
        raise HTTPException(status_code=400, detail="session_type must be 'notes' or 'qa'")

    new_session = ChatSession(
        title=session.title or "New Chat",
        session_type=session.session_type,
        user_id=current_user.id,
    )
    db.add(new_session)
    await db.flush()
    await db.refresh(new_session)
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
    return session


@router.post("/sessions/{session_id}/messages", response_model=ChatMessageResponse)
async def send_message(
    session_id: UUID,
    message: ChatMessageCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    session = await db.get(ChatSession, session_id)
    if not session or session.user_id != current_user.id:
        raise HTTPException(status_code=404, detail="Session not found")

    # Save user message
    user_msg = ChatMessage(
        session_id=session_id,
        role="user",
        content=message.content,
    )
    db.add(user_msg)
    await db.flush()

    # Generate AI response
    if session.session_type == "notes":
        # Get folder structure for context
        folder_result = await db.execute(
            select(Folder).where(Folder.user_id == current_user.id).order_by(Folder.path)
        )
        folders = folder_result.scalars().all()
        folder_structure = [{"path": f.path, "name": f.name} for f in folders]

        ai_result = await process_note_input(message.content, folder_structure)
        ai_response = f"""Hier ist mein Vorschlag für deine Notiz:

**Ordner:** `{ai_result['suggested_folder']}`
**Titel:** {ai_result['suggested_title']}

---

{ai_result['formatted_content']}

---

*Möchtest du diese Notiz so speichern? Du kannst den Vorschlag annehmen oder anpassen.*

<!-- AI_NOTE_DATA
{{"folder": "{ai_result['suggested_folder']}", "title": "{ai_result['suggested_title']}", "content": {repr(ai_result['formatted_content'])}}}
AI_NOTE_DATA -->"""

    elif session.session_type == "qa":
        # Get chat history
        history_result = await db.execute(
            select(ChatMessage)
            .where(ChatMessage.session_id == session_id)
            .order_by(ChatMessage.created_at)
        )
        history = history_result.scalars().all()
        chat_history = [{"role": m.role, "content": m.content} for m in history]

        # RAG search
        similar_notes = search_similar_notes(
            query=message.content,
            user_id=str(current_user.id),
            limit=5,
        )

        # Get full note content for context
        context_notes = []
        for sn in similar_notes:
            note = await db.get(Note, sn["note_id"])
            if note:
                folder = await db.get(Folder, note.folder_id)
                context_notes.append({
                    "title": note.title,
                    "folder_path": folder.path if folder else "",
                    "content_preview": note.content[:1000],
                })

        ai_response = await answer_with_rag(message.content, context_notes, chat_history)

        if similar_notes:
            sources = "\n\n---\n**Quellen:**\n"
            for sn in similar_notes:
                sources += f"- 📄 {sn['title']} (`{sn['folder_path']}`) - Relevanz: {sn['score']:.2f}\n"
            ai_response += sources
    else:
        ai_response = "Unbekannter Session-Typ."

    # Save assistant message
    assistant_msg = ChatMessage(
        session_id=session_id,
        role="assistant",
        content=ai_response,
    )
    db.add(assistant_msg)
    await db.flush()
    await db.refresh(assistant_msg)

    # Update session title if first message
    messages_count = await db.execute(
        select(ChatMessage).where(ChatMessage.session_id == session_id)
    )
    if len(messages_count.scalars().all()) <= 2:
        session.title = message.content[:50] + ("..." if len(message.content) > 50 else "")
        await db.flush()

    return ChatMessageResponse(
        id=assistant_msg.id,
        session_id=assistant_msg.session_id,
        role=assistant_msg.role,
        content=assistant_msg.content,
        created_at=assistant_msg.created_at,
    )
