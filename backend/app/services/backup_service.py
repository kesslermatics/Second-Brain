"""
Daily backup service with Qdrant snapshots + full user data backups.

- Creates a Qdrant snapshot of the brain_notes collection every day at 03:00 UTC
- Creates a full JSON backup of all user data every day at 03:00 UTC
- Keeps backups from the last 60 days
- Deletes older backups automatically
"""

import json
import os
from datetime import datetime, timezone, timedelta
from pathlib import Path
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from app.services.vector_service import _get_qdrant, COLLECTION_NAME

RETENTION_DAYS = 60
BACKUP_DIR = Path(os.environ.get("BACKUP_DIR", "backups"))

scheduler = AsyncIOScheduler()


async def create_qdrant_backup():
    """Create a Qdrant collection snapshot."""
    try:
        qdrant_client = _get_qdrant()
        snapshot = qdrant_client.create_snapshot(collection_name=COLLECTION_NAME)
        print(f"[Backup] Qdrant snapshot created: {snapshot.name}")
        return snapshot
    except Exception as e:
        print(f"[Backup] Error creating Qdrant snapshot: {e}")
        return None


async def create_full_backup():
    """Create a full JSON backup of all user data."""
    try:
        from app.database import async_session
        from app.models import User, Note, Folder, Tag, NoteVersion, ChatSession, ChatMessage, note_tags
        from sqlalchemy import select

        async with async_session() as db:
            # Get all users
            users_result = await db.execute(select(User))
            users = users_result.scalars().all()

            for user in users:
                uid = user.id
                folders_result = await db.execute(select(Folder).where(Folder.user_id == uid))
                folders = folders_result.scalars().all()

                notes_result = await db.execute(select(Note).where(Note.user_id == uid))
                notes = notes_result.scalars().all()

                tags_result = await db.execute(select(Tag).where(Tag.user_id == uid))
                tags = tags_result.scalars().all()

                note_tag_pairs = []
                for note in notes:
                    tag_result = await db.execute(
                        select(Tag.id).join(note_tags, Tag.id == note_tags.c.tag_id).where(note_tags.c.note_id == note.id)
                    )
                    for row in tag_result.all():
                        note_tag_pairs.append({"note_id": str(note.id), "tag_id": str(row[0])})

                sessions_result = await db.execute(select(ChatSession).where(ChatSession.user_id == uid))
                sessions = sessions_result.scalars().all()

                messages = []
                for session in sessions:
                    msg_result = await db.execute(
                        select(ChatMessage).where(ChatMessage.session_id == session.id)
                    )
                    messages.extend(msg_result.scalars().all())

                now = datetime.now(timezone.utc)
                backup_data = {
                    "meta": {
                        "created_at": now.isoformat(),
                        "label": "Automatisches Backup",
                        "user_id": str(uid),
                        "notes_count": len(notes),
                        "folders_count": len(folders),
                        "tags_count": len(tags),
                        "sessions_count": len(sessions),
                    },
                    "folders": [{"id": str(f.id), "name": f.name, "path": f.path, "parent_id": str(f.parent_id) if f.parent_id else None} for f in folders],
                    "tags": [{"id": str(t.id), "name": t.name, "name_lower": t.name_lower, "color": t.color} for t in tags],
                    "notes": [{"id": str(n.id), "title": n.title, "content": n.content, "note_type": n.note_type, "folder_id": str(n.folder_id), "created_at": n.created_at.isoformat() if n.created_at else None, "updated_at": n.updated_at.isoformat() if n.updated_at else None} for n in notes],
                    "note_tags": note_tag_pairs,
                    "sessions": [{"id": str(s.id), "title": s.title, "session_type": s.session_type, "created_at": s.created_at.isoformat() if s.created_at else None} for s in sessions],
                    "messages": [{"id": str(m.id), "session_id": str(m.session_id), "role": m.role, "content": m.content, "created_at": m.created_at.isoformat() if m.created_at else None} for m in messages],
                }

                user_backup_dir = BACKUP_DIR / str(uid)
                user_backup_dir.mkdir(parents=True, exist_ok=True)
                filename = f"{now.strftime('%Y%m%d_%H%M%S')}.json"
                filepath = user_backup_dir / filename

                with open(filepath, "w", encoding="utf-8") as f:
                    json.dump(backup_data, f, ensure_ascii=False)

                print(f"[Backup] Full backup created for user {uid}: {filename} ({len(notes)} notes)")

        # Rotate old backups
        await rotate_full_backups()

    except Exception as e:
        print(f"[Backup] Error creating full backup: {e}")


async def rotate_full_backups():
    """Delete full backups older than RETENTION_DAYS."""
    if not BACKUP_DIR.exists():
        return
    cutoff = datetime.now(timezone.utc) - timedelta(days=RETENTION_DAYS)
    deleted = 0
    for user_dir in BACKUP_DIR.iterdir():
        if not user_dir.is_dir():
            continue
        for f in user_dir.glob("*.json"):
            try:
                stat = f.stat()
                file_time = datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc)
                if file_time < cutoff:
                    f.unlink()
                    deleted += 1
            except Exception:
                continue
    if deleted:
        print(f"[Backup] Rotated {deleted} old backup files.")


async def rotate_qdrant_backups():
    """Delete Qdrant snapshots older than RETENTION_DAYS."""
    try:
        qdrant_client = _get_qdrant()
        snapshots = qdrant_client.list_snapshots(collection_name=COLLECTION_NAME)
        if not snapshots:
            return

        cutoff = datetime.now(timezone.utc) - timedelta(days=RETENTION_DAYS)
        deleted = 0

        for snap in snapshots:
            snap_time = snap.creation_time
            if snap_time and snap_time < cutoff:
                try:
                    qdrant_client.delete_snapshot(
                        collection_name=COLLECTION_NAME,
                        snapshot_name=snap.name,
                    )
                    deleted += 1
                except Exception as e:
                    print(f"[Backup] Error deleting snapshot {snap.name}: {e}")

        if deleted:
            print(f"[Backup] Rotated {deleted} old Qdrant snapshots.")
    except Exception as e:
        print(f"[Backup] Error rotating Qdrant snapshots: {e}")


async def daily_backup_job():
    """Run the daily backup: Qdrant snapshot + full user data backup."""
    print(f"[Backup] Starting daily backup at {datetime.now(timezone.utc).isoformat()}")
    await create_qdrant_backup()
    await create_full_backup()
    await rotate_qdrant_backups()
    print(f"[Backup] Daily backup complete.")


def start_backup_scheduler():
    """Start the APScheduler with the daily backup job at 03:00 UTC."""
    scheduler.add_job(
        daily_backup_job,
        trigger=CronTrigger(hour=3, minute=0, timezone="UTC"),
        id="daily_backup",
        name="Daily Full Backup (Qdrant + DB)",
        replace_existing=True,
    )
    scheduler.start()
    print(f"[Backup] Scheduler started — daily backup at 03:00 UTC, {RETENTION_DAYS}-day retention.")


def stop_backup_scheduler():
    """Gracefully shut down the scheduler."""
    if scheduler.running:
        scheduler.shutdown(wait=False)
        print("[Backup] Scheduler stopped.")

