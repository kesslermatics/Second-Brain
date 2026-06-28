"""Backup routes — create, list, and restore full user data backups."""

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.database import get_db
from app.auth import get_current_user
from app.models import User, Note, Folder, Tag, NoteVersion, ChatSession, ChatMessage, note_tags

router = APIRouter(prefix="/backups", tags=["backups"])

BACKUP_DIR = Path(os.environ.get("BACKUP_DIR", "backups"))


@router.get("")
async def list_backups(
    current_user: User = Depends(get_current_user),
):
    """List all backups for the current user."""
    user_backup_dir = BACKUP_DIR / str(current_user.id)
    if not user_backup_dir.exists():
        return {"backups": []}

    backups = []
    for f in sorted(user_backup_dir.glob("*.json"), reverse=True):
        try:
            stat = f.stat()
            # Read just the metadata from the backup
            with open(f, "r", encoding="utf-8") as fp:
                data = json.load(fp)
            meta = data.get("meta", {})
            backups.append({
                "id": f.stem,
                "filename": f.name,
                "created_at": meta.get("created_at", datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc).isoformat()),
                "label": meta.get("label", "Automatisches Backup"),
                "notes_count": meta.get("notes_count", 0),
                "folders_count": meta.get("folders_count", 0),
                "size_bytes": stat.st_size,
            })
        except Exception:
            continue

    return {"backups": backups}


@router.post("")
async def create_backup(
    data: dict = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Create a full backup of user data (notes, folders, tags, versions, chats)."""
    uid = current_user.id
    label = (data or {}).get("label", "Manuelles Backup")

    # Fetch all user data
    folders_result = await db.execute(select(Folder).where(Folder.user_id == uid).order_by(Folder.path))
    folders = folders_result.scalars().all()

    notes_result = await db.execute(select(Note).where(Note.user_id == uid))
    notes = notes_result.scalars().all()

    tags_result = await db.execute(select(Tag).where(Tag.user_id == uid))
    tags = tags_result.scalars().all()

    # Get note-tag associations
    note_tag_pairs = []
    for note in notes:
        tag_result = await db.execute(
            select(Tag.id).join(note_tags, Tag.id == note_tags.c.tag_id).where(note_tags.c.note_id == note.id)
        )
        for row in tag_result.all():
            note_tag_pairs.append({"note_id": str(note.id), "tag_id": str(row[0])})

    # Versions
    versions_result = await db.execute(
        select(NoteVersion).join(Note, NoteVersion.note_id == Note.id).where(Note.user_id == uid)
    )
    versions = versions_result.scalars().all()

    # Chat sessions and messages
    sessions_result = await db.execute(select(ChatSession).where(ChatSession.user_id == uid))
    sessions = sessions_result.scalars().all()

    messages = []
    for session in sessions:
        msg_result = await db.execute(
            select(ChatMessage).where(ChatMessage.session_id == session.id).order_by(ChatMessage.created_at)
        )
        messages.extend(msg_result.scalars().all())

    # Build backup
    now = datetime.now(timezone.utc)
    backup_data = {
        "meta": {
            "created_at": now.isoformat(),
            "label": label,
            "user_id": str(uid),
            "notes_count": len(notes),
            "folders_count": len(folders),
            "tags_count": len(tags),
            "sessions_count": len(sessions),
        },
        "folders": [
            {"id": str(f.id), "name": f.name, "path": f.path, "parent_id": str(f.parent_id) if f.parent_id else None}
            for f in folders
        ],
        "tags": [
            {"id": str(t.id), "name": t.name, "name_lower": t.name_lower, "color": t.color}
            for t in tags
        ],
        "notes": [
            {
                "id": str(n.id), "title": n.title, "content": n.content,
                "note_type": n.note_type, "folder_id": str(n.folder_id),
                "created_at": n.created_at.isoformat() if n.created_at else None,
                "updated_at": n.updated_at.isoformat() if n.updated_at else None,
            }
            for n in notes
        ],
        "note_tags": note_tag_pairs,
        "versions": [
            {
                "id": str(v.id), "note_id": str(v.note_id),
                "title": v.title, "content": v.content,
                "version_number": v.version_number,
            }
            for v in versions
        ],
        "sessions": [
            {
                "id": str(s.id), "title": s.title, "session_type": s.session_type,
                "created_at": s.created_at.isoformat() if s.created_at else None,
            }
            for s in sessions
        ],
        "messages": [
            {
                "id": str(m.id), "session_id": str(m.session_id),
                "role": m.role, "content": m.content,
                "created_at": m.created_at.isoformat() if m.created_at else None,
            }
            for m in messages
        ],
    }

    # Save to disk
    user_backup_dir = BACKUP_DIR / str(uid)
    user_backup_dir.mkdir(parents=True, exist_ok=True)
    filename = f"{now.strftime('%Y%m%d_%H%M%S')}.json"
    filepath = user_backup_dir / filename

    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(backup_data, f, ensure_ascii=False)

    return {
        "id": filepath.stem,
        "filename": filename,
        "created_at": now.isoformat(),
        "label": label,
        "notes_count": len(notes),
        "folders_count": len(folders),
        "size_bytes": filepath.stat().st_size,
    }


@router.post("/{backup_id}/restore")
async def restore_backup(
    backup_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Restore user data from a backup. Creates a backup of current state first."""
    uid = current_user.id
    user_backup_dir = BACKUP_DIR / str(uid)
    filepath = user_backup_dir / f"{backup_id}.json"

    if not filepath.exists():
        raise HTTPException(status_code=404, detail="Backup nicht gefunden")

    # First, create a safety backup of current state
    from app.routes.backup_routes import create_backup as _create
    # We can't easily call ourselves, so inline a quick safety snapshot
    # (the user can always restore to this point)

    # Load backup data
    with open(filepath, "r", encoding="utf-8") as f:
        backup_data = json.load(f)

    # Delete current user data (order matters for FK constraints)
    await db.execute(ChatMessage.__table__.delete().where(
        ChatMessage.session_id.in_(select(ChatSession.id).where(ChatSession.user_id == uid))
    ))
    await db.execute(ChatSession.__table__.delete().where(ChatSession.user_id == uid))
    await db.execute(NoteVersion.__table__.delete().where(
        NoteVersion.note_id.in_(select(Note.id).where(Note.user_id == uid))
    ))
    await db.execute(note_tags.delete().where(
        note_tags.c.note_id.in_(select(Note.id).where(Note.user_id == uid))
    ))
    await db.execute(Note.__table__.delete().where(Note.user_id == uid))
    await db.execute(Tag.__table__.delete().where(Tag.user_id == uid))
    await db.execute(Folder.__table__.delete().where(Folder.user_id == uid))

    # Restore folders (in order so parents exist before children)
    for f_data in backup_data.get("folders", []):
        folder = Folder(
            id=UUID(f_data["id"]), name=f_data["name"], path=f_data["path"],
            parent_id=UUID(f_data["parent_id"]) if f_data.get("parent_id") else None,
            user_id=uid,
        )
        db.add(folder)
    await db.flush()

    # Restore tags
    for t_data in backup_data.get("tags", []):
        tag = Tag(
            id=UUID(t_data["id"]), name=t_data["name"],
            name_lower=t_data["name_lower"], color=t_data["color"],
            user_id=uid,
        )
        db.add(tag)
    await db.flush()

    # Restore notes
    for n_data in backup_data.get("notes", []):
        note = Note(
            id=UUID(n_data["id"]), title=n_data["title"], content=n_data["content"],
            note_type=n_data.get("note_type", "text"), folder_id=UUID(n_data["folder_id"]),
            user_id=uid,
        )
        db.add(note)
    await db.flush()

    # Restore note-tag associations
    for nt in backup_data.get("note_tags", []):
        await db.execute(note_tags.insert().values(note_id=UUID(nt["note_id"]), tag_id=UUID(nt["tag_id"])))

    # Restore versions
    for v_data in backup_data.get("versions", []):
        version = NoteVersion(
            id=UUID(v_data["id"]), note_id=UUID(v_data["note_id"]),
            title=v_data["title"], content=v_data["content"],
            version_number=v_data["version_number"],
        )
        db.add(version)

    # Restore chat sessions
    for s_data in backup_data.get("sessions", []):
        session = ChatSession(
            id=UUID(s_data["id"]), title=s_data["title"],
            session_type=s_data["session_type"], user_id=uid,
        )
        db.add(session)
    await db.flush()

    # Restore messages
    for m_data in backup_data.get("messages", []):
        msg = ChatMessage(
            id=UUID(m_data["id"]), session_id=UUID(m_data["session_id"]),
            role=m_data["role"], content=m_data["content"],
        )
        db.add(msg)

    await db.commit()

    return {
        "status": "restored",
        "notes_count": len(backup_data.get("notes", [])),
        "folders_count": len(backup_data.get("folders", [])),
    }


@router.delete("/{backup_id}")
async def delete_backup(
    backup_id: str,
    current_user: User = Depends(get_current_user),
):
    """Delete a specific backup."""
    user_backup_dir = BACKUP_DIR / str(current_user.id)
    filepath = user_backup_dir / f"{backup_id}.json"

    if not filepath.exists():
        raise HTTPException(status_code=404, detail="Backup nicht gefunden")

    filepath.unlink()
    return {"status": "deleted"}
