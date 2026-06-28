"""
Agent Routes — agentic workspace with persistent chat sessions.
Uses the existing ChatSession/ChatMessage models with session_type='agent'.
"""

import json
import os
import uuid as _uuid
from pathlib import Path
from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks, UploadFile, File, Form
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
from uuid import UUID
from pydantic import BaseModel
from typing import Optional, List

from app.database import get_db
from app.auth import get_current_user
from app.models import User, Note, Folder, Tag, NoteVersion, note_tags, ChatSession, ChatMessage, Image
from app.schemas import ChatMessageResponse
from app.services.agent_service import run_agent
from app.services.ai_service import generate_chat_title
from app.services.vision_service import describe_image, describe_image_from_bytes
from app.services.vector_service import upsert_note_embedding, delete_note_embedding
from app.config import get_settings

router = APIRouter(prefix="/agent", tags=["agent"])

UPLOAD_DIR = Path(os.environ.get("UPLOAD_DIR", "uploads"))
ALLOWED_IMAGE_TYPES = {"image/png", "image/jpeg", "image/gif", "image/webp"}


class AgentMessageRequest(BaseModel):
    content: str
    auto_accept: bool = False


class ProposalApplyRequest(BaseModel):
    proposals: list[dict]


def _build_url(user_id: str, filename: str) -> str:
    settings = get_settings()
    backend_url = settings.BACKEND_URL or "http://localhost:8000"
    return f"{backend_url}/uploads/{user_id}/{filename}"


@router.post("/sessions/{session_id}/messages")
async def agent_send_message(
    session_id: UUID,
    background_tasks: BackgroundTasks,
    content: str = Form(...),
    auto_accept: bool = Form(False),
    images: List[UploadFile] = File(None),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Send a message to the agent within a session.
    Supports multipart form data with optional image uploads.
    Images are analyzed with Vision AI and their descriptions are added to context.
    """
    # Verify session
    session = await db.get(ChatSession, session_id)
    if not session or session.user_id != current_user.id:
        raise HTTPException(status_code=404, detail="Session not found")
    if session.session_type != "agent":
        raise HTTPException(status_code=400, detail="Not an agent session")

    # Process images if uploaded
    image_descriptions = []
    image_urls = []
    if images:
        for img_file in images:
            if not img_file.content_type or img_file.content_type not in ALLOWED_IMAGE_TYPES:
                continue
            img_bytes = await img_file.read()
            if len(img_bytes) == 0:
                continue

            # Save to disk
            user_dir = UPLOAD_DIR / str(current_user.id)
            user_dir.mkdir(parents=True, exist_ok=True)
            ext_map = {"image/png": ".png", "image/jpeg": ".jpg", "image/gif": ".gif", "image/webp": ".webp"}
            ext = ext_map.get(img_file.content_type, ".png")
            unique_name = f"{_uuid.uuid4().hex}{ext}"
            file_path = user_dir / unique_name
            with open(file_path, "wb") as f:
                f.write(img_bytes)

            file_url = _build_url(str(current_user.id), unique_name)
            image_urls.append(file_url)

            # Save to DB
            img_record = Image(
                original_filename=img_file.filename or f"pasted{ext}",
                stored_filename=unique_name,
                content_type=img_file.content_type,
                file_size=len(img_bytes),
                file_path=str(file_path),
                user_id=current_user.id,
            )
            db.add(img_record)
            await db.flush()
            await db.refresh(img_record)

            # Analyze with Vision
            try:
                description = await describe_image_from_bytes(img_bytes, img_file.content_type)
                img_record.description = description
                img_record.embedded = True
                image_descriptions.append({
                    "filename": img_file.filename or unique_name,
                    "url": file_url,
                    "description": description,
                    "image_id": str(img_record.id),
                })
            except Exception as e:
                image_descriptions.append({
                    "filename": img_file.filename or unique_name,
                    "url": file_url,
                    "description": f"(Bild konnte nicht analysiert werden: {str(e)[:100]})",
                    "image_id": str(img_record.id),
                })

    # Build the user message content (include image info if present)
    user_content = content
    if image_descriptions:
        img_context = "\n\n---\n**Angehängte Bilder:**\n"
        for desc in image_descriptions:
            img_context += f"\n📷 **{desc['filename']}**\n"
            img_context += f"Beschreibung: {desc['description']}\n"
            img_context += f"URL: {desc['url']}\n"
        user_content += img_context

    # Save user message
    user_msg = ChatMessage(
        session_id=session_id,
        role="user",
        content=user_content,
    )
    db.add(user_msg)
    await db.flush()

    # Load full chat history from DB
    history_result = await db.execute(
        select(ChatMessage)
        .where(ChatMessage.session_id == session_id)
        .order_by(ChatMessage.created_at)
    )
    all_messages = history_result.scalars().all()
    chat_history = [{"role": m.role, "content": m.content} for m in all_messages]

    # Run agent with full history
    result = await run_agent(
        instruction=user_content,
        user_id=str(current_user.id),
        db=db,
        chat_history=chat_history[:-1],
        auto_accept=auto_accept,
        image_context=image_descriptions if image_descriptions else None,
    )

    # Build the assistant message content
    agent_response = result.get("response", "")
    proposals = result.get("proposals", [])
    steps = result.get("steps", [])

    metadata = {}
    if proposals:
        metadata["proposals"] = proposals
    if steps:
        metadata["steps"] = steps

    stored_content = agent_response
    if metadata:
        stored_content += f"\n\n<!-- AGENT_META\n{json.dumps(metadata, ensure_ascii=False)}\nAGENT_META -->"

    # Save assistant message
    assistant_msg = ChatMessage(
        session_id=session_id,
        role="assistant",
        content=stored_content,
    )
    db.add(assistant_msg)
    await db.flush()
    await db.refresh(assistant_msg)

    # Auto-accept proposals if enabled
    apply_result = None
    if auto_accept and proposals:
        apply_result = await _apply_proposals(
            proposals=proposals,
            user_id=current_user.id,
            db=db,
            background_tasks=background_tasks,
        )

    # Auto-generate title on first message
    messages_count = await db.execute(
        select(func.count(ChatMessage.id)).where(ChatMessage.session_id == session_id)
    )
    count = messages_count.scalar()
    if count <= 2:
        try:
            ai_title = await generate_chat_title(content)
            session.title = ai_title
        except Exception:
            session.title = content[:50] + ("..." if len(content) > 50 else "")
        await db.flush()

    await db.commit()

    return {
        "message": {
            "id": str(assistant_msg.id),
            "session_id": str(session_id),
            "role": "assistant",
            "content": agent_response,
            "created_at": assistant_msg.created_at.isoformat(),
        },
        "steps": steps,
        "proposals": proposals,
        "apply_result": apply_result,
        "image_urls": image_urls,
    }


@router.post("/apply")
async def agent_apply_proposals(
    request: ProposalApplyRequest,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Apply accepted proposals (create, update, delete notes)."""
    result = await _apply_proposals(
        proposals=request.proposals,
        user_id=current_user.id,
        db=db,
        background_tasks=background_tasks,
    )
    return result


# ── Proposal application logic ────────────────────────────────────────

async def _apply_proposals(
    proposals: list[dict],
    user_id: UUID,
    db: AsyncSession,
    background_tasks: BackgroundTasks = None,
) -> dict:
    applied = 0
    errors = []
    created_notes = []
    updated_notes = []
    deleted_notes = []

    for p in proposals:
        ptype = p.get("type")
        try:
            if ptype == "create":
                result = await _apply_create(p, user_id, db, background_tasks)
                created_notes.append(result)
                applied += 1
            elif ptype == "update":
                result = await _apply_update(p, user_id, db, background_tasks)
                updated_notes.append(result)
                applied += 1
            elif ptype == "delete":
                result = await _apply_delete(p, user_id, db, background_tasks)
                deleted_notes.append(result)
                applied += 1
            else:
                errors.append(f"Unbekannter Proposal-Typ: {ptype}")
        except Exception as e:
            errors.append(f"Fehler bei {ptype}: {str(e)}")

    await db.commit()
    return {
        "applied": applied,
        "errors": errors,
        "created_notes": created_notes,
        "updated_notes": updated_notes,
        "deleted_notes": deleted_notes,
    }


async def _apply_create(p: dict, user_id: UUID, db: AsyncSession, background_tasks=None) -> dict:
    folder_path = p.get("folder_path", "")
    title = p.get("title", "Neue Notiz")
    content = p.get("content", "")
    tag_names = p.get("tags", [])

    folder = await _ensure_folder_path(folder_path, user_id, db)
    note = Note(title=title, content=content, note_type="text", folder_id=folder.id, user_id=user_id)
    db.add(note)
    await db.flush()
    await db.refresh(note)

    for tag_name in tag_names:
        tag = await _get_or_create_tag(tag_name, user_id, db)
        note.tags.append(tag)
    await db.flush()

    if background_tasks:
        background_tasks.add_task(upsert_note_embedding, str(note.id), str(user_id), note.title, note.content, folder.path)

    return {"note_id": str(note.id), "title": note.title, "folder_path": folder.path}


async def _apply_update(p: dict, user_id: UUID, db: AsyncSession, background_tasks=None) -> dict:
    note_id = p.get("note_id")
    if not note_id:
        raise ValueError("note_id fehlt")
    note = await db.get(Note, UUID(note_id))
    if not note or note.user_id != user_id:
        raise ValueError("Notiz nicht gefunden")

    # Version snapshot
    max_ver = await db.execute(
        select(func.coalesce(func.max(NoteVersion.version_number), 0)).where(NoteVersion.note_id == note.id)
    )
    version = NoteVersion(note_id=note.id, title=note.title, content=note.content, version_number=max_ver.scalar() + 1)
    db.add(version)

    if p.get("new_title"):
        note.title = p["new_title"]
    if p.get("new_content"):
        note.content = p["new_content"]
    await db.flush()

    folder = await db.get(Folder, note.folder_id)
    if background_tasks:
        background_tasks.add_task(upsert_note_embedding, str(note.id), str(user_id), note.title, note.content, folder.path if folder else "")

    return {"note_id": str(note.id), "title": note.title, "folder_path": folder.path if folder else ""}


async def _apply_delete(p: dict, user_id: UUID, db: AsyncSession, background_tasks=None) -> str:
    note_id = p.get("note_id")
    if not note_id:
        raise ValueError("note_id fehlt")
    note = await db.get(Note, UUID(note_id))
    if not note or note.user_id != user_id:
        raise ValueError("Notiz nicht gefunden")
    await db.delete(note)
    await db.flush()
    if background_tasks:
        background_tasks.add_task(delete_note_embedding, note_id)
    return note_id


async def _ensure_folder_path(path: str, user_id: UUID, db: AsyncSession) -> Folder:
    if not path:
        path = "Allgemein"
    result = await db.execute(select(Folder).where(Folder.path == path, Folder.user_id == user_id))
    folder = result.scalar_one_or_none()
    if folder:
        return folder

    parts = path.split("/")
    current_path = ""
    parent_id = None
    for part in parts:
        current_path = f"{current_path}/{part}" if current_path else part
        result = await db.execute(select(Folder).where(Folder.path == current_path, Folder.user_id == user_id))
        existing = result.scalar_one_or_none()
        if existing:
            parent_id = existing.id
            continue
        new_folder = Folder(name=part, path=current_path, parent_id=parent_id, user_id=user_id)
        db.add(new_folder)
        await db.flush()
        await db.refresh(new_folder)
        parent_id = new_folder.id
        folder = new_folder
    return folder


async def _get_or_create_tag(name: str, user_id: UUID, db: AsyncSession) -> Tag:
    import random
    name_lower = name.strip().lower()
    result = await db.execute(select(Tag).where(Tag.name_lower == name_lower, Tag.user_id == user_id))
    tag = result.scalar_one_or_none()
    if tag:
        return tag
    colors = ['#3b82f6', '#ef4444', '#10b981', '#f59e0b', '#8b5cf6', '#ec4899', '#06b6d4', '#84cc16']
    tag = Tag(name=name.strip(), name_lower=name_lower, color=random.choice(colors), user_id=user_id)
    db.add(tag)
    await db.flush()
    await db.refresh(tag)
    return tag
