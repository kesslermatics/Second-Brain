"""
Agent Routes — agentic workspace endpoint for multi-step AI operations on notes.
"""

import json
from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
from uuid import UUID
from pydantic import BaseModel
from typing import Optional, List

from app.database import get_db
from app.auth import get_current_user
from app.models import User, Note, Folder, Tag, NoteVersion, note_tags
from app.schemas import NoteResponse, TagResponse
from app.services.agent_service import run_agent
from app.services.vector_service import upsert_note_embedding, delete_note_embedding

router = APIRouter(prefix="/agent", tags=["agent"])


class AgentRunRequest(BaseModel):
    instruction: str
    auto_accept: bool = False


class ProposalApplyRequest(BaseModel):
    proposals: list[dict]


class ProposalApplyResult(BaseModel):
    applied: int
    errors: list[str]
    created_notes: list[dict]
    updated_notes: list[dict]
    deleted_notes: list[str]


@router.post("/run")
async def agent_run(
    request: AgentRunRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Run the agent with the given instruction. Returns steps + proposals.
    If auto_accept is True, proposals are applied immediately.
    """
    result = await run_agent(
        instruction=request.instruction,
        user_id=str(current_user.id),
        db=db,
        auto_accept=request.auto_accept,
    )

    # If auto_accept, apply proposals immediately
    if request.auto_accept and result.get("proposals"):
        apply_result = await _apply_proposals(
            proposals=result["proposals"],
            user_id=current_user.id,
            db=db,
        )
        result["apply_result"] = apply_result

    return result


@router.post("/apply", response_model=ProposalApplyResult)
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


async def _apply_proposals(
    proposals: list[dict],
    user_id: UUID,
    db: AsyncSession,
    background_tasks: BackgroundTasks = None,
) -> dict:
    """Apply a list of proposals to the database."""
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
    """Create a new note from a proposal."""
    folder_path = p.get("folder_path", "")
    title = p.get("title", "Neue Notiz")
    content = p.get("content", "")
    tag_names = p.get("tags", [])

    # Find or create folder
    folder = await _ensure_folder_path(folder_path, user_id, db)

    # Create note
    note = Note(
        title=title,
        content=content,
        note_type="text",
        folder_id=folder.id,
        user_id=user_id,
    )
    db.add(note)
    await db.flush()
    await db.refresh(note)

    # Attach tags
    for tag_name in tag_names:
        tag = await _get_or_create_tag(tag_name, user_id, db)
        note.tags.append(tag)
    await db.flush()

    # Embed in background
    if background_tasks:
        background_tasks.add_task(
            upsert_note_embedding,
            note_id=str(note.id),
            user_id=str(user_id),
            title=note.title,
            content=note.content,
            folder_path=folder.path,
        )

    return {
        "note_id": str(note.id),
        "title": note.title,
        "folder_path": folder.path,
    }


async def _apply_update(p: dict, user_id: UUID, db: AsyncSession, background_tasks=None) -> dict:
    """Update an existing note from a proposal."""
    note_id = p.get("note_id")
    if not note_id:
        raise ValueError("note_id fehlt im Update-Proposal")

    note = await db.get(Note, UUID(note_id))
    if not note or note.user_id != user_id:
        raise ValueError(f"Notiz {note_id} nicht gefunden oder kein Zugriff")

    # Save version before update
    max_ver_result = await db.execute(
        select(func.coalesce(func.max(NoteVersion.version_number), 0))
        .where(NoteVersion.note_id == note.id)
    )
    next_version = max_ver_result.scalar() + 1
    version = NoteVersion(
        note_id=note.id,
        title=note.title,
        content=note.content,
        version_number=next_version,
    )
    db.add(version)

    # Apply changes
    if p.get("new_title"):
        note.title = p["new_title"]
    if p.get("new_content"):
        note.content = p["new_content"]

    await db.flush()

    folder = await db.get(Folder, note.folder_id)

    # Re-embed in background
    if background_tasks:
        background_tasks.add_task(
            upsert_note_embedding,
            note_id=str(note.id),
            user_id=str(user_id),
            title=note.title,
            content=note.content,
            folder_path=folder.path if folder else "",
        )

    return {
        "note_id": str(note.id),
        "title": note.title,
        "folder_path": folder.path if folder else "",
    }


async def _apply_delete(p: dict, user_id: UUID, db: AsyncSession, background_tasks=None) -> str:
    """Delete a note from a proposal."""
    note_id = p.get("note_id")
    if not note_id:
        raise ValueError("note_id fehlt im Delete-Proposal")

    note = await db.get(Note, UUID(note_id))
    if not note or note.user_id != user_id:
        raise ValueError(f"Notiz {note_id} nicht gefunden oder kein Zugriff")

    await db.delete(note)
    await db.flush()

    if background_tasks:
        background_tasks.add_task(delete_note_embedding, note_id)

    return note_id


async def _ensure_folder_path(path: str, user_id: UUID, db: AsyncSession) -> Folder:
    """Ensure a folder path exists, creating folders as needed."""
    if not path:
        path = "Allgemein"

    # Check if folder exists
    result = await db.execute(
        select(Folder).where(Folder.path == path, Folder.user_id == user_id)
    )
    folder = result.scalar_one_or_none()
    if folder:
        return folder

    # Create folder hierarchy
    parts = path.split("/")
    current_path = ""
    parent_id = None

    for part in parts:
        current_path = f"{current_path}/{part}" if current_path else part
        result = await db.execute(
            select(Folder).where(Folder.path == current_path, Folder.user_id == user_id)
        )
        existing = result.scalar_one_or_none()
        if existing:
            parent_id = existing.id
            continue

        new_folder = Folder(
            name=part,
            path=current_path,
            parent_id=parent_id,
            user_id=user_id,
        )
        db.add(new_folder)
        await db.flush()
        await db.refresh(new_folder)
        parent_id = new_folder.id
        folder = new_folder

    return folder


async def _get_or_create_tag(name: str, user_id: UUID, db: AsyncSession) -> Tag:
    """Get existing tag or create a new one."""
    import random

    name_lower = name.strip().lower()
    result = await db.execute(
        select(Tag).where(Tag.name_lower == name_lower, Tag.user_id == user_id)
    )
    tag = result.scalar_one_or_none()
    if tag:
        return tag

    colors = ['#3b82f6', '#ef4444', '#10b981', '#f59e0b', '#8b5cf6', '#ec4899', '#06b6d4', '#84cc16']
    tag = Tag(
        name=name.strip(),
        name_lower=name_lower,
        color=random.choice(colors),
        user_id=user_id,
    )
    db.add(tag)
    await db.flush()
    await db.refresh(tag)
    return tag
