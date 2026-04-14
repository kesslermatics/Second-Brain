from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from typing import List
from uuid import UUID
from app.database import get_db
from app.auth import get_current_user
from app.models import User, Note, Folder
from app.schemas import NoteCreate, NoteUpdate, NoteResponse, NoteListResponse
from app.services.vector_service import upsert_note_embedding, delete_note_embedding

router = APIRouter(prefix="/notes", tags=["notes"])


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
    return NoteResponse(
        id=note.id,
        title=note.title,
        content=note.content,
        folder_id=note.folder_id,
        folder_path=folder.path if folder else None,
        created_at=note.created_at,
        updated_at=note.updated_at,
    )


@router.post("/", response_model=NoteResponse, status_code=status.HTTP_201_CREATED)
async def create_note(
    note: NoteCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    folder = await db.get(Folder, note.folder_id)
    if not folder or folder.user_id != current_user.id:
        raise HTTPException(status_code=404, detail="Folder not found")

    new_note = Note(
        title=note.title,
        content=note.content,
        folder_id=note.folder_id,
        user_id=current_user.id,
    )
    db.add(new_note)
    await db.flush()
    await db.refresh(new_note)

    try:
        upsert_note_embedding(
            note_id=str(new_note.id),
            user_id=str(current_user.id),
            title=new_note.title,
            content=new_note.content,
            folder_path=folder.path,
        )
    except Exception as e:
        print(f"Error creating embedding: {e}")

    return NoteResponse(
        id=new_note.id,
        title=new_note.title,
        content=new_note.content,
        folder_id=new_note.folder_id,
        folder_path=folder.path,
        created_at=new_note.created_at,
        updated_at=new_note.updated_at,
    )


@router.put("/{note_id}", response_model=NoteResponse)
async def update_note(
    note_id: UUID,
    note_update: NoteUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    note = await db.get(Note, note_id)
    if not note or note.user_id != current_user.id:
        raise HTTPException(status_code=404, detail="Note not found")

    if note_update.title is not None:
        note.title = note_update.title
    if note_update.content is not None:
        note.content = note_update.content
    if note_update.folder_id is not None:
        folder = await db.get(Folder, note_update.folder_id)
        if not folder or folder.user_id != current_user.id:
            raise HTTPException(status_code=404, detail="Target folder not found")
        note.folder_id = note_update.folder_id

    await db.flush()
    await db.refresh(note)

    folder = await db.get(Folder, note.folder_id)
    try:
        upsert_note_embedding(
            note_id=str(note.id),
            user_id=str(current_user.id),
            title=note.title,
            content=note.content,
            folder_path=folder.path if folder else "",
        )
    except Exception as e:
        print(f"Error updating embedding: {e}")

    return NoteResponse(
        id=note.id,
        title=note.title,
        content=note.content,
        folder_id=note.folder_id,
        folder_path=folder.path if folder else None,
        created_at=note.created_at,
        updated_at=note.updated_at,
    )


@router.delete("/{note_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_note(
    note_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    note = await db.get(Note, note_id)
    if not note or note.user_id != current_user.id:
        raise HTTPException(status_code=404, detail="Note not found")

    try:
        delete_note_embedding(str(note_id))
    except Exception as e:
        print(f"Error deleting embedding: {e}")

    await db.delete(note)
