import json
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from typing import List
from uuid import UUID
from app.database import get_db
from app.auth import get_current_user
from app.models import User, ChatSession, ChatMessage, Note, Folder, UserSettings, Image, Tag
from app.schemas import (
    ChatSessionCreate, ChatSessionResponse, ChatSessionDetailResponse,
    ChatMessageCreate, ChatMessageResponse,
)
from app.services.ai_service import process_note_input, answer_with_rag, generate_chat_title
from app.services.vector_service import hybrid_search

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

    # Load user's custom prompt settings
    settings_result = await db.execute(
        select(UserSettings).where(UserSettings.user_id == current_user.id)
    )
    user_settings = settings_result.scalar_one_or_none()

    # Generate AI response
    if session.session_type == "notes":
        # Get folder structure for context
        folder_result = await db.execute(
            select(Folder).where(Folder.user_id == current_user.id).order_by(Folder.path)
        )
        folders = folder_result.scalars().all()
        folder_structure = [{"path": f.path, "name": f.name} for f in folders]

        # Get existing tags for AI context
        tag_result = await db.execute(
            select(Tag).where(Tag.user_id == current_user.id).order_by(Tag.name)
        )
        all_tags = tag_result.scalars().all()
        existing_tag_names = [t.name for t in all_tags]

        custom_note_prompt = user_settings.note_prompt if user_settings else None
        ai_result = await process_note_input(
            message.content, folder_structure,
            custom_prompt=custom_note_prompt,
            existing_tags=existing_tag_names,
        )

        # Resolve suggested tags to IDs (create new ones if needed)
        tag_ids = []
        tag_display = []
        for tag_name in ai_result.get('suggested_tags', []):
            tag_lower = tag_name.strip().lower()
            if not tag_lower:
                continue
            # Check if tag already exists
            found_tag = None
            for t in all_tags:
                if t.name_lower == tag_lower:
                    found_tag = t
                    break
            if not found_tag:
                # Create new tag with a random color
                import random
                colors = ['#3b82f6', '#ef4444', '#10b981', '#f59e0b', '#8b5cf6', '#ec4899', '#06b6d4', '#84cc16']
                found_tag = Tag(
                    name=tag_name.strip(),
                    name_lower=tag_lower,
                    color=random.choice(colors),
                    user_id=current_user.id,
                )
                db.add(found_tag)
                await db.flush()
                await db.refresh(found_tag)
                all_tags.append(found_tag)
            tag_ids.append(str(found_tag.id))
            tag_display.append(found_tag.name)

        note_data_json = json.dumps({
            "folder": ai_result['suggested_folder'],
            "title": ai_result['suggested_title'],
            "content": ai_result['formatted_content'],
            "tag_ids": tag_ids,
        }, ensure_ascii=False)

        tags_line = f"\n**Tags:** {', '.join(f'`{t}`' for t in tag_display)}" if tag_display else ""

        ai_response = f"""Hier ist mein Vorschlag für deine Notiz:

**Ordner:** `{ai_result['suggested_folder']}`
**Titel:** {ai_result['suggested_title']}{tags_line}

---

{ai_result['formatted_content']}

---

*Möchtest du diese Notiz so speichern? Du kannst den Vorschlag annehmen oder anpassen.*

<!-- AI_NOTE_DATA
{note_data_json}
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

        # Hybrid search (vector + full-text, RRF fusion)
        similar_notes = await hybrid_search(
            query=message.content,
            user_id=str(current_user.id),
            db=db,
            limit=10,
        )

        # Batch-load all notes at once instead of one-by-one
        note_ids_to_load = [
            sn["note_id"] for sn in similar_notes
            if sn.get("type", "note") == "note"
        ]

        notes_map = {}
        if note_ids_to_load:
            notes_result = await db.execute(
                select(Note, Folder.path)
                .join(Folder, Note.folder_id == Folder.id)
                .where(Note.id.in_(note_ids_to_load))
            )
            for note_obj, folder_path in notes_result.all():
                notes_map[str(note_obj.id)] = (note_obj, folder_path)

        context_notes = []
        for sn in similar_notes:
            result_type = sn.get("type", "note")
            if result_type == "image":
                context_notes.append({
                    "title": sn["title"],
                    "folder_path": sn.get("folder_path", ""),
                    "content_preview": sn.get("content_preview", ""),
                })
            else:
                entry = notes_map.get(sn["note_id"])
                if entry:
                    note_obj, folder_path = entry
                    context_notes.append({
                        "title": note_obj.title,
                        "folder_path": folder_path,
                        "content_preview": note_obj.content[:2000],
                    })

        custom_qa_prompt = user_settings.qa_prompt if user_settings else None
        ai_response = await answer_with_rag(message.content, context_notes, chat_history, custom_prompt=custom_qa_prompt)

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

    # Auto-generate title with AI on first message
    messages_count = await db.execute(
        select(ChatMessage).where(ChatMessage.session_id == session_id)
    )
    if len(messages_count.scalars().all()) <= 2:
        try:
            ai_title = await generate_chat_title(message.content)
            session.title = ai_title
        except Exception:
            session.title = message.content[:50] + ("..." if len(message.content) > 50 else "")
        await db.flush()

    return ChatMessageResponse(
        id=assistant_msg.id,
        session_id=assistant_msg.session_id,
        role=assistant_msg.role,
        content=assistant_msg.content,
        created_at=assistant_msg.created_at,
    )
