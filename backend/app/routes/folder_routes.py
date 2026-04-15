from fastapi import APIRouter, Depends, HTTPException, status, BackgroundTasks
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from sqlalchemy.orm import selectinload
from typing import List, Optional
from uuid import UUID
from app.database import get_db
from app.auth import get_current_user
from app.models import User, Folder, Note
from app.schemas import FolderCreate, FolderResponse, FolderTreeResponse, NoteListResponse
from app.services.vector_service import delete_note_embedding

router = APIRouter(prefix="/folders", tags=["folders"])


def build_tree(folders: list[Folder], notes_by_folder: dict, parent_id=None) -> list[dict]:
    """Build tree structure from flat folder list."""
    tree = []
    for folder in folders:
        if folder.parent_id == parent_id:
            folder_notes = notes_by_folder.get(folder.id, [])
            children = build_tree(folders, notes_by_folder, folder.id)
            tree.append(
                FolderTreeResponse(
                    id=folder.id,
                    name=folder.name,
                    path=folder.path,
                    parent_id=folder.parent_id,
                    children=children,
                    notes=[
                        NoteListResponse(
                            id=n.id,
                            title=n.title,
                            note_type=getattr(n, 'note_type', 'text') or 'text',
                            folder_id=n.folder_id,
                            created_at=n.created_at,
                            updated_at=n.updated_at,
                        )
                        for n in folder_notes
                    ],
                )
            )
    return tree


@router.get("/", response_model=List[FolderResponse])
async def list_folders(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    result = await db.execute(
        select(Folder).where(Folder.user_id == current_user.id).order_by(Folder.path)
    )
    return result.scalars().all()


@router.get("/tree", response_model=List[FolderTreeResponse])
async def get_folder_tree(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    folder_result = await db.execute(
        select(Folder).where(Folder.user_id == current_user.id).order_by(Folder.path)
    )
    folders = folder_result.scalars().all()

    note_result = await db.execute(
        select(Note).where(Note.user_id == current_user.id)
    )
    notes = note_result.scalars().all()

    notes_by_folder = {}
    for note in notes:
        notes_by_folder.setdefault(note.folder_id, []).append(note)

    return build_tree(folders, notes_by_folder)


@router.post("/", response_model=FolderResponse, status_code=status.HTTP_201_CREATED)
async def create_folder(
    folder: FolderCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if folder.parent_id:
        parent = await db.get(Folder, folder.parent_id)
        if not parent or parent.user_id != current_user.id:
            raise HTTPException(status_code=404, detail="Parent folder not found")
        path = f"{parent.path}/{folder.name}"
    else:
        path = folder.name

    existing = await db.execute(
        select(Folder).where(Folder.path == path, Folder.user_id == current_user.id)
    )
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=409, detail="Folder already exists at this path")

    new_folder = Folder(
        name=folder.name,
        path=path,
        parent_id=folder.parent_id,
        user_id=current_user.id,
    )
    db.add(new_folder)
    await db.flush()
    await db.refresh(new_folder)
    return new_folder


@router.post("/ensure-path", response_model=FolderResponse)
async def ensure_folder_path(
    data: dict,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Create all folders in a path if they don't exist. Returns the leaf folder."""
    path = data.get("path", "").strip("/")
    if not path:
        raise HTTPException(status_code=400, detail="Path required")

    parts = path.split("/")
    parent_id = None
    current_path = ""
    last_folder = None

    for part in parts:
        current_path = f"{current_path}/{part}" if current_path else part

        result = await db.execute(
            select(Folder).where(
                Folder.path == current_path,
                Folder.user_id == current_user.id,
            )
        )
        folder = result.scalar_one_or_none()

        if not folder:
            folder = Folder(
                name=part,
                path=current_path,
                parent_id=parent_id,
                user_id=current_user.id,
            )
            db.add(folder)
            await db.flush()
            await db.refresh(folder)

        parent_id = folder.id
        last_folder = folder

    return last_folder


@router.delete("/{folder_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_folder(
    folder_id: UUID,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    folder = await db.get(Folder, folder_id)
    if not folder or folder.user_id != current_user.id:
        raise HTTPException(status_code=404, detail="Folder not found")

    # Collect all note IDs in this folder and all subfolders for Qdrant cleanup
    all_folders = await db.execute(
        select(Folder).where(Folder.user_id == current_user.id)
    )
    all_folders_list = all_folders.scalars().all()

    # BFS to find all descendant folder IDs
    folder_ids_to_delete = set()
    queue = [folder_id]
    while queue:
        current_id = queue.pop(0)
        folder_ids_to_delete.add(current_id)
        for f in all_folders_list:
            if f.parent_id == current_id and f.id not in folder_ids_to_delete:
                queue.append(f.id)

    # Find all notes in these folders
    notes_result = await db.execute(
        select(Note.id).where(Note.folder_id.in_(folder_ids_to_delete))
    )
    note_ids = [str(nid) for (nid,) in notes_result.all()]

    # Schedule Qdrant embedding deletions in background
    for nid in note_ids:
        background_tasks.add_task(delete_note_embedding, nid)

    # SQLAlchemy cascade will handle children + notes
    await db.delete(folder)
