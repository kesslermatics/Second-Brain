"""
Image routes — upload, list, describe (Gemini Vision), delete.
Every uploaded image is:
  1. stored on disk
  2. persisted in the images DB table
  3. described by Gemini Vision → description stored in DB
  4. description embedded in Qdrant for RAG retrieval
"""
import os
import uuid as _uuid
from pathlib import Path
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Query, BackgroundTasks
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from uuid import UUID

from app.database import get_db, async_session
from app.auth import get_current_user
from app.models import User, Image, Folder, Note
from app.schemas import ImageResponse, ImageListResponse
from app.config import get_settings
from app.services.vision_service import describe_image
from app.services.vector_service import upsert_image_embedding, delete_image_embedding

router = APIRouter(prefix="/images", tags=["images"])

UPLOAD_DIR = Path(os.environ.get("UPLOAD_DIR", "uploads"))
ALLOWED_IMAGE_TYPES = {"image/png", "image/jpeg", "image/gif", "image/webp", "image/svg+xml"}
MAX_FILE_SIZE = 20 * 1024 * 1024  # 20 MB


def _build_url(user_id: str, stored_filename: str) -> str:
    settings = get_settings()
    backend_url = settings.BACKEND_URL or "http://localhost:8000"
    return f"{backend_url}/uploads/{user_id}/{stored_filename}"


async def _process_image_ai(image_id: str, file_path: str, original_filename: str, user_id: str, folder_path: str, note_title: str):
    """Background task: describe image with Gemini Vision and embed in Qdrant."""
    try:
        description = await describe_image(file_path)
    except Exception as e:
        print(f"[Vision] Failed to describe image {image_id}: {e}")
        description = f"Bild: {original_filename} (Beschreibung konnte nicht generiert werden)"

    # Update DB
    async with async_session() as db:
        try:
            img = await db.get(Image, _uuid.UUID(image_id))
            if img:
                img.description = description
                img.embedded = True
                await db.commit()
        except Exception as e:
            print(f"[Vision] DB update failed for {image_id}: {e}")
            await db.rollback()

    # Embed in Qdrant
    try:
        upsert_image_embedding(
            image_id=image_id,
            user_id=user_id,
            original_filename=original_filename,
            description=description,
            folder_path=folder_path,
            note_title=note_title,
        )
    except Exception as e:
        print(f"[Vision] Qdrant upsert failed for {image_id}: {e}")


@router.post("/upload", response_model=ImageResponse, status_code=201)
async def upload_image(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    folder_id: Optional[str] = None,
    note_id: Optional[str] = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Upload an image, persist to DB, and trigger AI description + RAG embedding."""
    if file.content_type not in ALLOWED_IMAGE_TYPES:
        raise HTTPException(status_code=400, detail=f"Nur Bilder erlaubt. Erlaubt: {', '.join(sorted(ALLOWED_IMAGE_TYPES))}")

    content = await file.read()
    if len(content) > MAX_FILE_SIZE:
        raise HTTPException(status_code=400, detail=f"Datei zu groß. Max: {MAX_FILE_SIZE // (1024*1024)} MB")

    # Resolve optional foreign keys
    folder_uuid = None
    folder_path = ""
    if folder_id:
        folder = await db.get(Folder, UUID(folder_id))
        if folder and folder.user_id == current_user.id:
            folder_uuid = folder.id
            folder_path = folder.path

    note_uuid = None
    note_title = ""
    if note_id:
        note = await db.get(Note, UUID(note_id))
        if note and note.user_id == current_user.id:
            note_uuid = note.id
            note_title = note.title

    # Save to disk
    user_dir = UPLOAD_DIR / str(current_user.id)
    user_dir.mkdir(parents=True, exist_ok=True)

    ext = Path(file.filename).suffix if file.filename else ".png"
    stored_name = f"{_uuid.uuid4().hex}{ext}"
    file_path = user_dir / stored_name

    with open(file_path, "wb") as f:
        f.write(content)

    # Persist to DB
    img = Image(
        original_filename=file.filename or stored_name,
        stored_filename=stored_name,
        content_type=file.content_type,
        file_size=len(content),
        file_path=str(file_path),
        folder_id=folder_uuid,
        note_id=note_uuid,
        user_id=current_user.id,
    )
    db.add(img)
    await db.flush()
    await db.refresh(img)

    # Trigger background AI analysis
    background_tasks.add_task(
        _process_image_ai,
        str(img.id),
        str(file_path),
        img.original_filename,
        str(current_user.id),
        folder_path,
        note_title,
    )

    return ImageResponse(
        id=img.id,
        original_filename=img.original_filename,
        stored_filename=img.stored_filename,
        content_type=img.content_type,
        file_size=img.file_size,
        url=_build_url(str(current_user.id), stored_name),
        description=img.description,
        folder_id=img.folder_id,
        note_id=img.note_id,
        embedded=img.embedded,
        created_at=img.created_at,
    )


@router.post("/paste", response_model=ImageResponse, status_code=201)
async def paste_image(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    note_id: Optional[str] = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Upload a pasted image from clipboard. Same persistence + AI pipeline."""
    if file.content_type not in ALLOWED_IMAGE_TYPES:
        raise HTTPException(status_code=400, detail="Nur Bilder können eingefügt werden")

    content = await file.read()
    if len(content) > MAX_FILE_SIZE:
        raise HTTPException(status_code=400, detail="Bild zu groß")

    note_uuid = None
    note_title = ""
    folder_path = ""
    if note_id:
        note = await db.get(Note, UUID(note_id))
        if note and note.user_id == current_user.id:
            note_uuid = note.id
            note_title = note.title
            folder = await db.get(Folder, note.folder_id)
            folder_path = folder.path if folder else ""

    user_dir = UPLOAD_DIR / str(current_user.id)
    user_dir.mkdir(parents=True, exist_ok=True)

    ext_map = {"image/png": ".png", "image/jpeg": ".jpg", "image/gif": ".gif", "image/webp": ".webp", "image/svg+xml": ".svg"}
    ext = ext_map.get(file.content_type, ".png")
    stored_name = f"{_uuid.uuid4().hex}{ext}"
    file_path = user_dir / stored_name

    with open(file_path, "wb") as f:
        f.write(content)

    img = Image(
        original_filename=file.filename or f"pasted{ext}",
        stored_filename=stored_name,
        content_type=file.content_type,
        file_size=len(content),
        file_path=str(file_path),
        note_id=note_uuid,
        user_id=current_user.id,
    )
    db.add(img)
    await db.flush()
    await db.refresh(img)

    background_tasks.add_task(
        _process_image_ai,
        str(img.id),
        str(file_path),
        img.original_filename,
        str(current_user.id),
        folder_path,
        note_title,
    )

    return ImageResponse(
        id=img.id,
        original_filename=img.original_filename,
        stored_filename=img.stored_filename,
        content_type=img.content_type,
        file_size=img.file_size,
        url=_build_url(str(current_user.id), stored_name),
        description=img.description,
        folder_id=img.folder_id,
        note_id=img.note_id,
        embedded=img.embedded,
        created_at=img.created_at,
    )


@router.get("/", response_model=ImageListResponse)
async def list_images(
    folder_id: Optional[str] = None,
    note_id: Optional[str] = None,
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """List images, optionally filtered by folder or note."""
    query = select(Image).where(Image.user_id == current_user.id)
    if folder_id:
        query = query.where(Image.folder_id == UUID(folder_id))
    if note_id:
        query = query.where(Image.note_id == UUID(note_id))
    query = query.order_by(Image.created_at.desc()).limit(limit).offset(offset)

    result = await db.execute(query)
    images = result.scalars().all()

    # Count total
    from sqlalchemy import func
    count_q = select(func.count(Image.id)).where(Image.user_id == current_user.id)
    if folder_id:
        count_q = count_q.where(Image.folder_id == UUID(folder_id))
    if note_id:
        count_q = count_q.where(Image.note_id == UUID(note_id))
    total = (await db.execute(count_q)).scalar() or 0

    return ImageListResponse(
        images=[
            ImageResponse(
                id=img.id,
                original_filename=img.original_filename,
                stored_filename=img.stored_filename,
                content_type=img.content_type,
                file_size=img.file_size,
                url=_build_url(str(current_user.id), img.stored_filename),
                description=img.description,
                folder_id=img.folder_id,
                note_id=img.note_id,
                embedded=img.embedded,
                created_at=img.created_at,
            )
            for img in images
        ],
        total=total,
    )


@router.get("/{image_id}", response_model=ImageResponse)
async def get_image(
    image_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Get a single image by ID."""
    img = await db.get(Image, image_id)
    if not img or img.user_id != current_user.id:
        raise HTTPException(status_code=404, detail="Bild nicht gefunden")

    return ImageResponse(
        id=img.id,
        original_filename=img.original_filename,
        stored_filename=img.stored_filename,
        content_type=img.content_type,
        file_size=img.file_size,
        url=_build_url(str(current_user.id), img.stored_filename),
        description=img.description,
        folder_id=img.folder_id,
        note_id=img.note_id,
        embedded=img.embedded,
        created_at=img.created_at,
    )


@router.post("/{image_id}/reanalyze", response_model=ImageResponse)
async def reanalyze_image(
    image_id: UUID,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Re-trigger AI description and Qdrant embedding for an image."""
    img = await db.get(Image, image_id)
    if not img or img.user_id != current_user.id:
        raise HTTPException(status_code=404, detail="Bild nicht gefunden")

    folder_path = ""
    if img.folder_id:
        folder = await db.get(Folder, img.folder_id)
        folder_path = folder.path if folder else ""

    note_title = ""
    if img.note_id:
        note = await db.get(Note, img.note_id)
        note_title = note.title if note else ""

    background_tasks.add_task(
        _process_image_ai,
        str(img.id),
        img.file_path,
        img.original_filename,
        str(current_user.id),
        folder_path,
        note_title,
    )

    return ImageResponse(
        id=img.id,
        original_filename=img.original_filename,
        stored_filename=img.stored_filename,
        content_type=img.content_type,
        file_size=img.file_size,
        url=_build_url(str(current_user.id), img.stored_filename),
        description=img.description,
        folder_id=img.folder_id,
        note_id=img.note_id,
        embedded=img.embedded,
        created_at=img.created_at,
    )


@router.delete("/{image_id}", status_code=204)
async def delete_image(
    image_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Delete an image from disk, DB, and Qdrant."""
    img = await db.get(Image, image_id)
    if not img or img.user_id != current_user.id:
        raise HTTPException(status_code=404, detail="Bild nicht gefunden")

    # Remove from disk
    try:
        file_path = Path(img.file_path)
        if file_path.exists():
            file_path.unlink()
    except Exception as e:
        print(f"Error deleting image file: {e}")

    # Remove from Qdrant
    try:
        delete_image_embedding(str(image_id))
    except Exception as e:
        print(f"Error deleting image embedding: {e}")

    await db.delete(img)
