from fastapi import APIRouter, Depends, HTTPException, status, BackgroundTasks
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
from typing import List
from uuid import UUID
import json
from app.database import get_db
from app.auth import get_current_user
from app.models import User, Note, Folder, Tag, NoteVersion
from app.schemas import NoteCreate, NoteUpdate, NoteResponse, NoteListResponse, TagResponse
from app.services.vector_service import upsert_note_embedding, delete_note_embedding

router = APIRouter(prefix="/notes", tags=["notes"])


def extract_excalidraw_text(content: str) -> str:
    """Extract readable text from Excalidraw JSON for embedding."""
    try:
        data = json.loads(content)
        elements = data.get("elements", [])
        texts = []
        for el in elements:
            if el.get("type") == "text" and el.get("text"):
                texts.append(el["text"])
            # Also get bound text from containers
            if el.get("boundElements"):
                for be in el["boundElements"]:
                    if be.get("type") == "text":
                        # text will be in its own element
                        pass
        return "\n".join(texts) if texts else "[Excalidraw Zeichnung]"
    except (json.JSONDecodeError, KeyError):
        return content[:500]


@router.get("/", response_model=List[NoteListResponse])
async def list_notes(
    folder_id: UUID = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    query = select(Note).where(Note.user_id == current_user.id)
    if folder_id:
        query = query.where(Note.folder_id == folder_id)
    query = query.order_by(Note.updated_at.desc())
    result = await db.execute(query)
    return result.scalars().all()


@router.get("/{note_id}", response_model=NoteResponse)
async def get_note(
    note_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    note = await db.get(Note, note_id)
    if not note or note.user_id != current_user.id:
        raise HTTPException(status_code=404, detail="Note not found")

    folder = await db.get(Folder, note.folder_id)

    # Load tags
    await db.refresh(note, ["tags"])
    tags = [TagResponse(id=t.id, name=t.name, color=t.color) for t in note.tags]

    return NoteResponse(
        id=note.id,
        title=note.title,
        content=note.content,
        note_type=note.note_type or "text",
        folder_id=note.folder_id,
        folder_path=folder.path if folder else None,
        tags=tags,
        created_at=note.created_at,
        updated_at=note.updated_at,
    )


@router.post("/", response_model=NoteResponse, status_code=status.HTTP_201_CREATED)
async def create_note(
    note: NoteCreate,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    folder = await db.get(Folder, note.folder_id)
    if not folder or folder.user_id != current_user.id:
        raise HTTPException(status_code=404, detail="Folder not found")

    new_note = Note(
        title=note.title,
        content=note.content,
        note_type=note.note_type or "text",
        folder_id=note.folder_id,
        user_id=current_user.id,
    )
    db.add(new_note)
    await db.flush()
    await db.refresh(new_note, ["tags"])

    # Attach tags if provided
    tags = []
    if note.tag_ids:
        for tag_id in note.tag_ids:
            tag = await db.get(Tag, tag_id)
            if tag and tag.user_id == current_user.id:
                new_note.tags.append(tag)
                tags.append(TagResponse(id=tag.id, name=tag.name, color=tag.color))
        await db.flush()

    embed_content = new_note.content
    if new_note.note_type == "excalidraw":
        embed_content = extract_excalidraw_text(new_note.content)
    background_tasks.add_task(
        upsert_note_embedding,
        note_id=str(new_note.id),
        user_id=str(current_user.id),
        title=new_note.title,
        content=embed_content,
        folder_path=folder.path,
    )

    return NoteResponse(
        id=new_note.id,
        title=new_note.title,
        content=new_note.content,
        note_type=new_note.note_type or "text",
        folder_id=new_note.folder_id,
        folder_path=folder.path,
        tags=tags,
        created_at=new_note.created_at,
        updated_at=new_note.updated_at,
    )


@router.put("/{note_id}", response_model=NoteResponse)
async def update_note(
    note_id: UUID,
    note_update: NoteUpdate,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    note = await db.get(Note, note_id)
    if not note or note.user_id != current_user.id:
        raise HTTPException(status_code=404, detail="Note not found")

    # Save current state as a version before changing
    if note_update.title is not None or note_update.content is not None:
        max_ver_result = await db.execute(
            select(func.coalesce(func.max(NoteVersion.version_number), 0))
            .where(NoteVersion.note_id == note_id)
        )
        next_version = max_ver_result.scalar() + 1
        version = NoteVersion(
            note_id=note_id,
            title=note.title,
            content=note.content,
            version_number=next_version,
        )
        db.add(version)

    if note_update.title is not None:
        note.title = note_update.title
    if note_update.content is not None:
        note.content = note_update.content
    if note_update.note_type is not None:
        note.note_type = note_update.note_type
    if note_update.folder_id is not None:
        folder = await db.get(Folder, note_update.folder_id)
        if not folder or folder.user_id != current_user.id:
            raise HTTPException(status_code=404, detail="Target folder not found")
        note.folder_id = note_update.folder_id

    # Update tags if provided
    if note_update.tag_ids is not None:
        await db.refresh(note, ["tags"])
        note.tags.clear()
        for tag_id in note_update.tag_ids:
            tag = await db.get(Tag, tag_id)
            if tag and tag.user_id == current_user.id:
                note.tags.append(tag)

    await db.flush()
    await db.refresh(note)

    folder = await db.get(Folder, note.folder_id)
    embed_content = note.content
    if (note.note_type or "text") == "excalidraw":
        embed_content = extract_excalidraw_text(note.content)
    background_tasks.add_task(
        upsert_note_embedding,
        note_id=str(note.id),
        user_id=str(current_user.id),
        title=note.title,
        content=embed_content,
        folder_path=folder.path if folder else "",
    )

    await db.refresh(note, ["tags"])
    tags = [TagResponse(id=t.id, name=t.name, color=t.color) for t in note.tags]

    return NoteResponse(
        id=note.id,
        title=note.title,
        content=note.content,
        note_type=note.note_type or "text",
        folder_id=note.folder_id,
        folder_path=folder.path if folder else None,
        tags=tags,
        created_at=note.created_at,
        updated_at=note.updated_at,
    )


@router.delete("/{note_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_note(
    note_id: UUID,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    note = await db.get(Note, note_id)
    if not note or note.user_id != current_user.id:
        raise HTTPException(status_code=404, detail="Note not found")

    background_tasks.add_task(delete_note_embedding, str(note_id))

    await db.delete(note)
