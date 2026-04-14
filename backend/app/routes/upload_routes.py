"""
Legacy upload routes — kept for backward compatibility with the rich text editor.
These routes also persist images to the DB and trigger AI description.
Non-image files are uploaded as before (disk only).
"""
import os
import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, BackgroundTasks
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.auth import get_current_user
from app.models import User, Image
from app.config import get_settings
from app.routes.image_routes import _process_image_ai

router = APIRouter(prefix="/uploads", tags=["uploads"])

UPLOAD_DIR = Path(os.environ.get("UPLOAD_DIR", "uploads"))
ALLOWED_IMAGE_TYPES = {"image/png", "image/jpeg", "image/gif", "image/webp", "image/svg+xml"}
ALLOWED_ATTACHMENT_TYPES = ALLOWED_IMAGE_TYPES | {
    "application/pdf",
    "text/plain",
    "application/json",
    "application/zip",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
}
MAX_FILE_SIZE = 20 * 1024 * 1024  # 20 MB


def _build_url(user_id: str, filename: str) -> str:
    settings = get_settings()
    backend_url = settings.BACKEND_URL or "http://localhost:8000"
    return f"{backend_url}/uploads/{user_id}/{filename}"


@router.post("/")
async def upload_file(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Upload a file (image or attachment). Images are also persisted to DB + AI-analyzed."""
    if file.content_type not in ALLOWED_ATTACHMENT_TYPES:
        raise HTTPException(
            status_code=400,
            detail=f"File type '{file.content_type}' not allowed.",
        )

    content = await file.read()
    if len(content) > MAX_FILE_SIZE:
        raise HTTPException(status_code=400, detail=f"File too large. Max: {MAX_FILE_SIZE // (1024*1024)} MB")

    user_dir = UPLOAD_DIR / str(current_user.id)
    user_dir.mkdir(parents=True, exist_ok=True)

    ext = Path(file.filename).suffix if file.filename else ""
    unique_name = f"{uuid.uuid4().hex}{ext}"
    file_path = user_dir / unique_name

    with open(file_path, "wb") as f:
        f.write(content)

    file_url = _build_url(str(current_user.id), unique_name)

    # If it's an image, also persist to images table + trigger AI
    if file.content_type in ALLOWED_IMAGE_TYPES:
        img = Image(
            original_filename=file.filename or unique_name,
            stored_filename=unique_name,
            content_type=file.content_type,
            file_size=len(content),
            file_path=str(file_path),
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
            "",
            "",
        )

    return {
        "url": file_url,
        "filename": file.filename,
        "size": len(content),
        "content_type": file.content_type,
    }


@router.post("/paste")
async def upload_pasted_image(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Upload a pasted image from clipboard. Also persisted + AI-analyzed."""
    if file.content_type not in ALLOWED_IMAGE_TYPES:
        raise HTTPException(status_code=400, detail="Only images can be pasted")

    content = await file.read()
    if len(content) > MAX_FILE_SIZE:
        raise HTTPException(status_code=400, detail="Image too large")

    user_dir = UPLOAD_DIR / str(current_user.id)
    user_dir.mkdir(parents=True, exist_ok=True)

    ext_map = {
        "image/png": ".png", "image/jpeg": ".jpg", "image/gif": ".gif",
        "image/webp": ".webp", "image/svg+xml": ".svg",
    }
    ext = ext_map.get(file.content_type, ".png")
    unique_name = f"{uuid.uuid4().hex}{ext}"
    file_path = user_dir / unique_name

    with open(file_path, "wb") as f:
        f.write(content)

    file_url = _build_url(str(current_user.id), unique_name)

    img = Image(
        original_filename=file.filename or f"pasted{ext}",
        stored_filename=unique_name,
        content_type=file.content_type,
        file_size=len(content),
        file_path=str(file_path),
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
        "",
        "",
    )

    return {
        "url": file_url,
        "filename": unique_name,
        "size": len(content),
        "content_type": file.content_type,
    }
