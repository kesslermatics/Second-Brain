import io
import json
import zipfile
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.database import get_db
from app.auth import get_current_user
from app.models import User, Note, Folder
from app.schemas import ExportRequest

router = APIRouter(prefix="/export", tags=["export"])


@router.post("")
async def export_notes(
    data: ExportRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Export notes as a ZIP of Markdown files or JSON."""
    uid = current_user.id

    if data.include_all:
        notes_result = await db.execute(
            select(Note, Folder.path)
            .join(Folder, Note.folder_id == Folder.id)
            .where(Note.user_id == uid)
            .order_by(Folder.path, Note.title)
        )
    elif data.folder_ids:
        # Get all folder IDs including subfolders
        all_folder_ids = set()
        for fid in data.folder_ids:
            folder = await db.get(Folder, fid)
            if folder and folder.user_id == uid:
                # Include this folder and all subfolders
                sub_result = await db.execute(
                    select(Folder.id).where(
                        Folder.user_id == uid,
                        Folder.path.like(f"{folder.path}%"),
                    )
                )
                for row in sub_result.all():
                    all_folder_ids.add(row[0])

        notes_result = await db.execute(
            select(Note, Folder.path)
            .join(Folder, Note.folder_id == Folder.id)
            .where(Note.user_id == uid, Note.folder_id.in_(all_folder_ids))
            .order_by(Folder.path, Note.title)
        )
    elif data.note_ids:
        notes_result = await db.execute(
            select(Note, Folder.path)
            .join(Folder, Note.folder_id == Folder.id)
            .where(Note.user_id == uid, Note.id.in_(data.note_ids))
            .order_by(Folder.path, Note.title)
        )
    else:
        raise HTTPException(status_code=400, detail="Specify folder_ids, note_ids, or include_all")

    rows = notes_result.all()

    # Build ZIP
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, 'w', zipfile.ZIP_DEFLATED) as zf:
        for note, folder_path in rows:
            safe_title = note.title.replace("/", "-").replace("\\", "-")

            if data.format == "json":
                file_content = json.dumps({
                    "id": str(note.id),
                    "title": note.title,
                    "content": note.content,
                    "folder_path": folder_path,
                    "created_at": note.created_at.isoformat(),
                    "updated_at": note.updated_at.isoformat(),
                }, ensure_ascii=False, indent=2)
                ext = ".json"
            else:
                file_content = f"# {note.title}\n\n{note.content}"
                ext = ".md"

            file_path = f"{folder_path}/{safe_title}{ext}"
            zf.writestr(file_path, file_content)

    buffer.seek(0)

    return StreamingResponse(
        buffer,
        media_type="application/zip",
        headers={"Content-Disposition": "attachment; filename=brain-export.zip"},
    )
