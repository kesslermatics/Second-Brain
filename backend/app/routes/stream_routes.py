"""Server-Sent Events streaming for chat responses."""

import json
import asyncio
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from uuid import UUID
from app.database import get_db, async_session
from app.auth import get_current_user
from app.models import User, ChatSession, ChatMessage, Note, Folder, UserSettings
from app.services.ai_service import get_gemini_model, DEFAULT_NOTE_PROMPT, DEFAULT_RAG_PROMPT, generate_chat_title
from app.services.vector_service import hybrid_search
import google.generativeai as genai

router = APIRouter(prefix="/chat", tags=["chat-stream"])


async def _stream_generate(prompt: str):
    """Generator that yields SSE events from Gemini streaming."""
    model = get_gemini_model()
    response = model.generate_content(prompt, stream=True)

    for chunk in response:
        if chunk.text:
            data = json.dumps({"type": "chunk", "content": chunk.text}, ensure_ascii=False)
            yield f"data: {data}\n\n"

    yield f"data: {json.dumps({'type': 'done'})}\n\n"


@router.post("/sessions/{session_id}/messages/stream")
async def stream_message(
    session_id: UUID,
    data: dict,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Send message and stream AI response via SSE."""
    content = data.get("content", "").strip()
    if not content:
        raise HTTPException(status_code=400, detail="Content required")

    session = await db.get(ChatSession, session_id)
    if not session or session.user_id != current_user.id:
        raise HTTPException(status_code=404, detail="Session not found")

    # Save user message
    user_msg = ChatMessage(session_id=session_id, role="user", content=content)
    db.add(user_msg)
    await db.flush()
    await db.commit()

    # Load custom prompts
    settings_result = await db.execute(
        select(UserSettings).where(UserSettings.user_id == current_user.id)
    )
    user_settings = settings_result.scalar_one_or_none()

    if session.session_type == "qa":
        # Build RAG prompt
        history_result = await db.execute(
            select(ChatMessage).where(ChatMessage.session_id == session_id).order_by(ChatMessage.created_at)
        )
        history = history_result.scalars().all()
        chat_history_entries = [{"role": m.role, "content": m.content} for m in history]

        similar_notes = await hybrid_search(
            query=content, user_id=str(current_user.id), db=db, limit=10
        )

        context_str = ""
        for sn in similar_notes:
            note = await db.get(Note, sn["note_id"])
            if note:
                folder = await db.get(Folder, note.folder_id)
                context_str += f"\n--- Notiz: {note.title} (Pfad: {folder.path if folder else ''}) ---\n"
                context_str += f"{note.content[:1000]}\n"

        history_str = ""
        for msg in chat_history_entries[-10:]:
            role = "Benutzer" if msg["role"] == "user" else "Assistent"
            history_str += f"{role}: {msg['content']}\n"
        chat_block = f"Bisheriger Chatverlauf:\n{history_str}" if history_str else ""

        template = (user_settings.qa_prompt if user_settings and user_settings.qa_prompt else DEFAULT_RAG_PROMPT)
        prompt = template.replace("{{KONTEXT}}", context_str).replace("{{CHATVERLAUF}}", chat_block).replace("{{FRAGE}}", content)

        # Build sources suffix
        sources_suffix = ""
        if similar_notes:
            sources_suffix = "\n\n---\n**Quellen:**\n"
            for sn in similar_notes:
                sources_suffix += f"- 📄 {sn['title']} (`{sn['folder_path']}`) - Relevanz: {sn['score']:.2f}\n"
    else:
        # For notes type, we don't stream (JSON parsing needed)
        raise HTTPException(status_code=400, detail="Streaming only supported for QA sessions")

    # Collect full response for saving, but stream chunks
    full_response_parts = []

    async def event_stream():
        model = get_gemini_model()
        response = model.generate_content(prompt, stream=True)

        for chunk in response:
            if chunk.text:
                full_response_parts.append(chunk.text)
                data = json.dumps({"type": "chunk", "content": chunk.text}, ensure_ascii=False)
                yield f"data: {data}\n\n"

        # Append sources
        if sources_suffix:
            full_response_parts.append(sources_suffix)
            data = json.dumps({"type": "chunk", "content": sources_suffix}, ensure_ascii=False)
            yield f"data: {data}\n\n"

        # Save the complete message to DB
        full_text = "".join(full_response_parts)
        async with async_session() as save_db:
            assistant_msg = ChatMessage(
                session_id=session_id, role="assistant", content=full_text
            )
            save_db.add(assistant_msg)

            # Update title if first message
            count_result = await save_db.execute(
                select(ChatMessage).where(ChatMessage.session_id == session_id)
            )
            existing = count_result.scalars().all()
            if len(existing) <= 1:
                s = await save_db.get(ChatSession, session_id)
                if s:
                    try:
                        ai_title = await generate_chat_title(content)
                        s.title = ai_title
                    except Exception:
                        s.title = content[:50] + ("..." if len(content) > 50 else "")

            await save_db.commit()

        done_data = json.dumps({"type": "done", "message_id": str(session_id)})
        yield f"data: {done_data}\n\n"

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
