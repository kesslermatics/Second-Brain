"""
Agent Routes — agentic workspace with persistent chat sessions.
Uses the existing ChatSession/ChatMessage models with session_type='agent'.
"""

import json
import os
import re
import asyncio
import uuid as _uuid
from pathlib import Path
from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks, UploadFile, File, Form
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, or_
from uuid import UUID
from pydantic import BaseModel
from typing import Optional, List

from app.database import get_db, async_session
from app.auth import get_current_user
from app.models import User, Note, Folder, Tag, NoteVersion, note_tags, ChatSession, ChatMessage, Image
from app.schemas import ChatMessageResponse
from app.services.agent_service import run_agent, run_agent_stream
from app.services.ai_service import generate_chat_title
from app.services.vector_service import upsert_note_embedding, delete_note_embedding
from app.config import get_settings

router = APIRouter(prefix="/agent", tags=["agent"])

UPLOAD_DIR = Path(os.environ.get("UPLOAD_DIR", "uploads"))
ALLOWED_IMAGE_TYPES = {"image/png", "image/jpeg", "image/gif", "image/webp"}
ALLOWED_DOCUMENT_TYPES = {"application/pdf", "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                          "application/msword", "text/plain", "text/markdown", "text/csv",
                          "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"}
ALLOWED_FILE_TYPES = ALLOWED_IMAGE_TYPES | ALLOWED_DOCUMENT_TYPES


class AgentMessageRequest(BaseModel):
    content: str
    auto_accept: bool = False


class ProposalApplyRequest(BaseModel):
    proposals: list[dict]


def _build_url(user_id: str, filename: str) -> str:
    settings = get_settings()
    backend_url = settings.BACKEND_URL or "http://localhost:8000"
    return f"{backend_url}/uploads/{user_id}/{filename}"


async def _process_uploaded_files(
    files: List[UploadFile],
    current_user: User,
    db: AsyncSession,
) -> tuple[list[dict], list[str]]:
    """Process uploaded files (images + documents). Returns (file_descriptions, file_urls)."""
    from app.services.vision_service import describe_image_from_bytes, analyze_document

    file_descriptions = []
    file_urls = []

    if not files:
        return file_descriptions, file_urls

    for uploaded_file in files:
        if not uploaded_file.content_type or uploaded_file.content_type not in ALLOWED_FILE_TYPES:
            continue
        file_bytes = await uploaded_file.read()
        if len(file_bytes) == 0:
            continue

        # Save to disk
        user_dir = UPLOAD_DIR / str(current_user.id)
        user_dir.mkdir(parents=True, exist_ok=True)

        ext_map = {
            "image/png": ".png", "image/jpeg": ".jpg", "image/gif": ".gif", "image/webp": ".webp",
            "application/pdf": ".pdf", "text/plain": ".txt", "text/markdown": ".md", "text/csv": ".csv",
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document": ".docx",
            "application/msword": ".doc",
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": ".xlsx",
        }
        ext = ext_map.get(uploaded_file.content_type, ".bin")
        unique_name = f"{_uuid.uuid4().hex}{ext}"
        file_path = user_dir / unique_name
        with open(file_path, "wb") as f:
            f.write(file_bytes)

        file_url = _build_url(str(current_user.id), unique_name)
        file_urls.append(file_url)

        # Save to DB (using Image model for all file types)
        file_record = Image(
            original_filename=uploaded_file.filename or f"file{ext}",
            stored_filename=unique_name,
            content_type=uploaded_file.content_type,
            file_size=len(file_bytes),
            file_path=str(file_path),
            user_id=current_user.id,
        )
        db.add(file_record)
        await db.flush()
        await db.refresh(file_record)

        # Analyze content based on file type
        is_image = uploaded_file.content_type in ALLOWED_IMAGE_TYPES
        try:
            if is_image:
                description = await describe_image_from_bytes(file_bytes, uploaded_file.content_type)
            else:
                description = await analyze_document(file_bytes, uploaded_file.content_type, uploaded_file.filename or unique_name)
            file_record.description = description
            file_record.embedded = True
        except Exception as e:
            description = f"(Datei konnte nicht analysiert werden: {str(e)[:100]})"

        file_descriptions.append({
            "filename": uploaded_file.filename or unique_name,
            "url": file_url,
            "description": description,
            "file_id": str(file_record.id),
            "type": "image" if is_image else "document",
            "content_type": uploaded_file.content_type,
            "size": len(file_bytes),
        })

    return file_descriptions, file_urls


@router.post("/sessions/{session_id}/messages")
async def agent_send_message(
    session_id: UUID,
    background_tasks: BackgroundTasks,
    content: str = Form(...),
    auto_accept: bool = Form(False),
    images: List[UploadFile] = File(None),
    files: List[UploadFile] = File(None),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Send a message to the agent within a session.
    Supports multipart form data with optional file uploads (images, PDFs, documents).
    Files are analyzed with AI and their descriptions are added to context.
    """
    # Verify session
    session = await db.get(ChatSession, session_id)
    if not session or session.user_id != current_user.id:
        raise HTTPException(status_code=404, detail="Session not found")
    if session.session_type != "agent":
        raise HTTPException(status_code=400, detail="Not an agent session")

    # Merge images and files fields (backwards compat + new field)
    all_files = []
    if images:
        all_files.extend(images)
    if files:
        all_files.extend(files)

    # Process all uploaded files
    file_descriptions, file_urls = await _process_uploaded_files(all_files, current_user, db)

    # Build the user message content (include file info if present)
    user_content = content
    if file_descriptions:
        file_context = "\n\n---\n**Angehängte Dateien:**\n"
        for desc in file_descriptions:
            icon = "📷" if desc["type"] == "image" else "📄"
            file_context += f"\n{icon} **{desc['filename']}**\n"
            file_context += f"Beschreibung: {desc['description']}\n"
            file_context += f"URL: {desc['url']}\n"
        user_content += file_context

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
        image_context=file_descriptions if file_descriptions else None,
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
        "image_urls": file_urls,
    }


@router.post("/sessions/{session_id}/messages/stream")
async def agent_stream_message(
    session_id: UUID,
    background_tasks: BackgroundTasks,
    content: str = Form(...),
    auto_accept: bool = Form(False),
    images: List[UploadFile] = File(None),
    files: List[UploadFile] = File(None),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Start a background agent job and return a job_id.

    The client immediately gets {"job_id": "..."} and opens
    GET /api/jobs/{job_id}/events to receive the SSE stream.
    The job survives tab switches and app changes — reconnect with ?from=N
    to replay missed events.
    """
    from app.services.job_store import job_store

    # Verify session
    session = await db.get(ChatSession, session_id)
    if not session or session.user_id != current_user.id:
        raise HTTPException(status_code=404, detail="Session not found")
    if session.session_type != "agent":
        raise HTTPException(status_code=400, detail="Not an agent session")

    # Merge images and files fields (backwards compat + new field)
    all_files = []
    if images:
        all_files.extend(images)
    if files:
        all_files.extend(files)

    # Process all uploaded files
    file_descriptions, file_urls = await _process_uploaded_files(all_files, current_user, db)

    # Build user message content
    user_content = content
    if file_descriptions:
        file_context = "\n\n---\n**Angehängte Dateien:**\n"
        for desc in file_descriptions:
            icon = "📷" if desc["type"] == "image" else "📄"
            file_context += f"\n{icon} **{desc['filename']}**\n"
            file_context += f"Beschreibung: {desc['description']}\n"
            file_context += f"URL: {desc['url']}\n"
        user_content += file_context

    # Save user message
    user_msg = ChatMessage(session_id=session_id, role="user", content=user_content)
    db.add(user_msg)
    await db.flush()

    # Load chat history
    history_result = await db.execute(
        select(ChatMessage)
        .where(ChatMessage.session_id == session_id)
        .order_by(ChatMessage.created_at)
    )
    all_messages = history_result.scalars().all()
    chat_history = [{"role": m.role, "content": m.content} for m in all_messages]

    await db.commit()

    # Snapshot for background job
    session_id_str = str(session_id)
    user_id_str = str(current_user.id)

    async def _generate_events():
        full_response_parts: list[str] = []
        all_proposals: list = []
        all_steps: list = []

        async with async_session() as bg_db:
            async for event in run_agent_stream(
                instruction=user_content,
                user_id=user_id_str,
                db=bg_db,
                chat_history=chat_history[:-1],
                auto_accept=auto_accept,
                image_context=file_descriptions if file_descriptions else None,
            ):
                event_type = event.get("type")

                if event_type == "thinking":
                    yield {"type": "thinking", "content": event["content"]}
                elif event_type == "chunk":
                    full_response_parts.append(event["content"])
                    yield {"type": "chunk", "content": event["content"]}
                elif event_type == "tool_call":
                    all_steps.append(event)
                    yield {"type": "tool_call", "content": event["content"]}
                elif event_type == "tool_result":
                    all_steps.append(event)
                    yield {"type": "tool_result", "content": event["content"]}
                elif event_type == "proposal":
                    all_proposals.append(event["proposal"])
                    yield {"type": "proposal", "proposal": event["proposal"]}
                elif event_type == "sources":
                    yield {"type": "sources", "sources": event.get("sources", [])}
                elif event_type == "done":
                    all_proposals = event.get("proposals", all_proposals)
                    all_steps = event.get("steps", all_steps)

            # Save assistant message to DB
            agent_response = "".join(full_response_parts)
            metadata: dict = {}
            if all_proposals:
                metadata["proposals"] = all_proposals
            if all_steps:
                metadata["steps"] = all_steps

            stored_content = agent_response
            if metadata:
                stored_content += f"\n\n<!-- AGENT_META\n{json.dumps(metadata, ensure_ascii=False)}\nAGENT_META -->"

            assistant_msg = ChatMessage(
                session_id=UUID(session_id_str), role="assistant", content=stored_content,
            )
            bg_db.add(assistant_msg)

            # Auto-generate title on first messages
            count_result = await bg_db.execute(
                select(func.count(ChatMessage.id)).where(ChatMessage.session_id == UUID(session_id_str))
            )
            count = count_result.scalar()
            if count <= 2:
                try:
                    ai_title = await generate_chat_title(content)
                    s = await bg_db.get(ChatSession, UUID(session_id_str))
                    if s:
                        s.title = ai_title
                except Exception:
                    s = await bg_db.get(ChatSession, UUID(session_id_str))
                    if s:
                        s.title = content[:50] + ("..." if len(content) > 50 else "")

            # Auto-accept proposals
            apply_result = None
            if auto_accept and all_proposals:
                apply_result = await _apply_proposals(
                    proposals=all_proposals,
                    user_id=current_user.id,
                    db=bg_db,
                    background_tasks=background_tasks,
                )

            await bg_db.commit()

        yield {
            "type": "done",
            "proposals": all_proposals,
            "steps": all_steps,
            "apply_result": apply_result,
            "image_urls": file_urls,
        }

    # Register job and fire the background task
    import uuid as _uuid_mod
    job_id = str(_uuid_mod.uuid4())
    job_store.create_job(job_id)
    asyncio.create_task(job_store.run_job(job_id, _generate_events()))

    return {"job_id": job_id}


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


class MarkAppliedRequest(BaseModel):
    message_id: str
    applied_indices: list[int]


@router.post("/mark-applied")
async def mark_proposals_applied(
    request: MarkAppliedRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Mark specific proposal indices as applied in the message metadata.
    This prevents re-applying proposals when the view is revisited."""
    msg = await db.get(ChatMessage, UUID(request.message_id))
    if not msg:
        raise HTTPException(status_code=404, detail="Message not found")

    # Verify ownership through session
    session = await db.get(ChatSession, msg.session_id)
    if not session or session.user_id != current_user.id:
        raise HTTPException(status_code=404, detail="Message not found")

    # Update the AGENT_META to include applied_indices
    content = msg.content
    meta_match = re.search(r'<!-- AGENT_META\n([\s\S]*?)\nAGENT_META -->', content)
    if meta_match:
        try:
            meta = json.loads(meta_match.group(1))
            existing = set(meta.get("applied_indices", []))
            existing.update(request.applied_indices)
            meta["applied_indices"] = sorted(existing)
            new_meta_str = json.dumps(meta, ensure_ascii=False)
            content = content[:meta_match.start()] + f"<!-- AGENT_META\n{new_meta_str}\nAGENT_META -->" + content[meta_match.end():]
            msg.content = content
            await db.commit()
        except (json.JSONDecodeError, Exception):
            pass

    return {"status": "ok"}


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
            elif ptype == "rename_note":
                result = await _apply_rename_note(p, user_id, db, background_tasks)
                updated_notes.append(result)
                applied += 1
            elif ptype == "move_note":
                result = await _apply_move_note(p, user_id, db, background_tasks)
                updated_notes.append(result)
                applied += 1
            elif ptype == "create_folder":
                await _apply_create_folder(p, user_id, db)
                applied += 1
            elif ptype == "rename_folder":
                await _apply_rename_folder(p, user_id, db, background_tasks)
                applied += 1
            elif ptype == "delete_folder":
                await _apply_delete_folder(p, user_id, db, background_tasks)
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
    attach_file_ids = p.get("attach_file_ids", [])

    folder = await _ensure_folder_path(folder_path, user_id, db)
    note = Note(title=title, content=content, note_type="text", folder_id=folder.id, user_id=user_id)
    db.add(note)
    await db.flush()
    await db.refresh(note)

    for tag_name in tag_names:
        tag = await _get_or_create_tag(tag_name, user_id, db)
        note.tags.append(tag)

    # Link attached files to this note and folder
    for file_id in attach_file_ids:
        try:
            file_record = await db.get(Image, UUID(file_id))
            if file_record and file_record.user_id == user_id:
                file_record.note_id = note.id
                file_record.folder_id = folder.id
        except (ValueError, TypeError):
            pass

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


async def _apply_rename_note(p: dict, user_id: UUID, db: AsyncSession, background_tasks=None) -> dict:
    note_id = p.get("note_id")
    new_title = p.get("new_title")
    if not note_id:
        raise ValueError("note_id fehlt")
    if not new_title:
        raise ValueError("new_title fehlt")
    note = await db.get(Note, UUID(note_id))
    if not note or note.user_id != user_id:
        raise ValueError("Notiz nicht gefunden")
    note.title = new_title
    await db.flush()
    folder = await db.get(Folder, note.folder_id)
    if background_tasks:
        background_tasks.add_task(upsert_note_embedding, str(note.id), str(user_id), note.title, note.content, folder.path if folder else "")
    return {"note_id": str(note.id), "title": note.title, "folder_path": folder.path if folder else ""}


async def _apply_move_note(p: dict, user_id: UUID, db: AsyncSession, background_tasks=None) -> dict:
    note_id = p.get("note_id")
    target_path = p.get("target_folder_path", "")
    if not note_id:
        raise ValueError("note_id fehlt")
    note = await db.get(Note, UUID(note_id))
    if not note or note.user_id != user_id:
        raise ValueError("Notiz nicht gefunden")
    folder = await _ensure_folder_path(target_path, user_id, db)
    note.folder_id = folder.id
    await db.flush()
    if background_tasks:
        background_tasks.add_task(upsert_note_embedding, str(note.id), str(user_id), note.title, note.content, folder.path)
    return {"note_id": str(note.id), "title": note.title, "folder_path": folder.path}


async def _apply_create_folder(p: dict, user_id: UUID, db: AsyncSession) -> dict:
    folder_path = p.get("folder_path", "")
    if not folder_path:
        raise ValueError("folder_path fehlt")
    folder = await _ensure_folder_path(folder_path, user_id, db)
    return {"folder_id": str(folder.id), "path": folder.path}


async def _apply_rename_folder(p: dict, user_id: UUID, db: AsyncSession, background_tasks=None) -> dict:
    folder_path = p.get("folder_path", "")
    new_name = p.get("new_name", "")
    if not folder_path or not new_name:
        raise ValueError("folder_path und new_name erforderlich")

    result = await db.execute(
        select(Folder).where(Folder.path == folder_path, Folder.user_id == user_id)
    )
    folder = result.scalar_one_or_none()
    if not folder:
        raise ValueError(f"Ordner '{folder_path}' nicht gefunden")

    old_path = folder.path
    # Compute new path (keep parent prefix, swap the leaf name)
    if "/" in old_path:
        prefix = old_path.rsplit("/", 1)[0]
        new_path = f"{prefix}/{new_name}"
    else:
        new_path = new_name

    folder.name = new_name
    folder.path = new_path

    # Update descendant paths + re-embed affected notes
    affected_note_ids = await _repath_descendants(old_path, new_path, user_id, db)
    await db.flush()

    if background_tasks:
        for nid in affected_note_ids:
            note = await db.get(Note, nid)
            if note:
                f = await db.get(Folder, note.folder_id)
                background_tasks.add_task(upsert_note_embedding, str(note.id), str(user_id), note.title, note.content, f.path if f else "")

    return {"folder_id": str(folder.id), "path": new_path}


async def _apply_delete_folder(p: dict, user_id: UUID, db: AsyncSession, background_tasks=None) -> dict:
    from sqlalchemy import delete as sa_delete, or_ as sa_or
    from app.models import NoteLink

    folder_path = p.get("folder_path", "")
    if not folder_path:
        raise ValueError("folder_path fehlt")

    result = await db.execute(
        select(Folder).where(Folder.path == folder_path, Folder.user_id == user_id)
    )
    folder = result.scalar_one_or_none()
    if not folder:
        raise ValueError(f"Ordner '{folder_path}' nicht gefunden")

    # Collect this folder + all descendants (by path prefix)
    desc_result = await db.execute(
        select(Folder).where(
            Folder.user_id == user_id,
            or_(Folder.path == folder_path, Folder.path.like(f"{folder_path}/%")),
        )
    )
    folders_to_delete = desc_result.scalars().all()
    folder_ids = [f.id for f in folders_to_delete]

    # Find all notes in these folders
    notes_result = await db.execute(
        select(Note.id).where(Note.folder_id.in_(folder_ids))
    )
    note_ids = [nid for (nid,) in notes_result.all()]

    if note_ids:
        await db.execute(
            sa_delete(NoteLink).where(
                sa_or(
                    NoteLink.source_note_id.in_(note_ids),
                    NoteLink.target_note_id.in_(note_ids),
                )
            )
        )
        await db.execute(sa_delete(note_tags).where(note_tags.c.note_id.in_(note_ids)))
        await db.execute(sa_delete(NoteVersion).where(NoteVersion.note_id.in_(note_ids)))
        await db.execute(sa_delete(Note).where(Note.id.in_(note_ids)))
        if background_tasks:
            for nid in note_ids:
                background_tasks.add_task(delete_note_embedding, str(nid))

    # Delete folders deepest-first
    for f in sorted(folders_to_delete, key=lambda x: len(x.path), reverse=True):
        await db.delete(f)
    await db.flush()

    return {"deleted_folder": folder_path, "deleted_notes": len(note_ids)}


async def _repath_descendants(old_path: str, new_path: str, user_id: UUID, db: AsyncSession) -> list:
    """Update the path of all descendant folders after a rename/move. Returns affected note IDs."""
    result = await db.execute(
        select(Folder).where(
            Folder.user_id == user_id,
            Folder.path.like(f"{old_path}/%"),
        )
    )
    descendants = result.scalars().all()
    affected_folder_ids = []
    for child in descendants:
        child.path = new_path + child.path[len(old_path):]
        affected_folder_ids.append(child.id)

    # Also include the renamed folder itself for note re-embedding
    root_result = await db.execute(
        select(Folder).where(Folder.path == new_path, Folder.user_id == user_id)
    )
    root = root_result.scalar_one_or_none()
    if root:
        affected_folder_ids.append(root.id)

    if not affected_folder_ids:
        return []

    notes_result = await db.execute(
        select(Note.id).where(Note.folder_id.in_(affected_folder_ids))
    )
    return [nid for (nid,) in notes_result.all()]


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
