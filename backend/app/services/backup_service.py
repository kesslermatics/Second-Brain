"""
Daily Qdrant collection backup with 60-day rotation.

Uses Qdrant's built-in snapshot API:
- Creates a snapshot of the brain_notes collection every day at 03:00 UTC
- Keeps snapshots from the last 60 days
- Deletes older snapshots automatically
"""

from datetime import datetime, timezone, timedelta
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from app.services.vector_service import qdrant_client, COLLECTION_NAME

RETENTION_DAYS = 60

scheduler = AsyncIOScheduler()


async def create_backup():
    """Create a Qdrant collection snapshot."""
    try:
        snapshot = qdrant_client.create_snapshot(collection_name=COLLECTION_NAME)
        print(f"[Backup] Snapshot created: {snapshot.name}")
        return snapshot
    except Exception as e:
        print(f"[Backup] Error creating snapshot: {e}")
        return None


async def rotate_backups():
    """Delete snapshots older than RETENTION_DAYS."""
    try:
        snapshots = qdrant_client.list_snapshots(collection_name=COLLECTION_NAME)
        if not snapshots:
            print("[Backup] No snapshots found, nothing to rotate.")
            return

        cutoff = datetime.now(timezone.utc) - timedelta(days=RETENTION_DAYS)
        deleted = 0

        for snap in snapshots:
            # Qdrant snapshot names contain the timestamp,
            # use the creation_time attribute if available
            snap_time = snap.creation_time
            if snap_time and snap_time < cutoff:
                try:
                    qdrant_client.delete_snapshot(
                        collection_name=COLLECTION_NAME,
                        snapshot_name=snap.name,
                    )
                    deleted += 1
                    print(f"[Backup] Deleted old snapshot: {snap.name}")
                except Exception as e:
                    print(f"[Backup] Error deleting snapshot {snap.name}: {e}")

        total = len(snapshots) - deleted
        print(f"[Backup] Rotation done. Deleted {deleted} old snapshots, {total} remaining.")
    except Exception as e:
        print(f"[Backup] Error listing snapshots for rotation: {e}")


async def daily_backup_job():
    """Run the daily backup: create snapshot, then rotate old ones."""
    print(f"[Backup] Starting daily backup at {datetime.now(timezone.utc).isoformat()}")
    await create_backup()
    await rotate_backups()
    print(f"[Backup] Daily backup complete.")


def start_backup_scheduler():
    """Start the APScheduler with the daily backup job at 03:00 UTC."""
    scheduler.add_job(
        daily_backup_job,
        trigger=CronTrigger(hour=3, minute=0, timezone="UTC"),
        id="daily_qdrant_backup",
        name="Daily Qdrant Collection Backup",
        replace_existing=True,
    )
    scheduler.start()
    print(f"[Backup] Scheduler started — daily backup at 03:00 UTC, {RETENTION_DAYS}-day retention.")


def stop_backup_scheduler():
    """Gracefully shut down the scheduler."""
    if scheduler.running:
        scheduler.shutdown(wait=False)
        print("[Backup] Scheduler stopped.")
