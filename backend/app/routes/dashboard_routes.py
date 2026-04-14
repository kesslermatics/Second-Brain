from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, text
from datetime import datetime, timezone, timedelta
from app.database import get_db
from app.auth import get_current_user
from app.models import User, Note, Folder, Tag, FlashCard, note_tags
from app.schemas import DashboardResponse

router = APIRouter(prefix="/dashboard", tags=["dashboard"])


@router.get("", response_model=DashboardResponse)
async def get_dashboard(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    uid = current_user.id
    now = datetime.now(timezone.utc)
    week_ago = now - timedelta(days=7)
    month_ago = now - timedelta(days=30)

    # Basic counts
    total_notes = (await db.execute(
        select(func.count(Note.id)).where(Note.user_id == uid)
    )).scalar() or 0

    total_folders = (await db.execute(
        select(func.count(Folder.id)).where(Folder.user_id == uid)
    )).scalar() or 0

    total_tags = (await db.execute(
        select(func.count(Tag.id)).where(Tag.user_id == uid)
    )).scalar() or 0

    total_flashcards = (await db.execute(
        select(func.count(FlashCard.id)).where(FlashCard.user_id == uid)
    )).scalar() or 0

    # Word count
    word_result = await db.execute(
        select(func.sum(func.length(Note.content))).where(Note.user_id == uid)
    )
    total_chars = word_result.scalar() or 0
    total_words = total_chars // 5  # rough estimate

    # Notes this week / month
    notes_this_week = (await db.execute(
        select(func.count(Note.id)).where(Note.user_id == uid, Note.created_at >= week_ago)
    )).scalar() or 0

    notes_this_month = (await db.execute(
        select(func.count(Note.id)).where(Note.user_id == uid, Note.created_at >= month_ago)
    )).scalar() or 0

    # Top folders (by note count)
    top_folders_result = await db.execute(
        select(Folder.path, func.count(Note.id).label("cnt"))
        .join(Note, Note.folder_id == Folder.id)
        .where(Note.user_id == uid)
        .group_by(Folder.path)
        .order_by(func.count(Note.id).desc())
        .limit(10)
    )
    top_folders = [{"path": r.path, "count": r.cnt} for r in top_folders_result.all()]

    # Top tags
    top_tags_result = await db.execute(
        select(Tag.name, func.count(note_tags.c.note_id).label("cnt"))
        .join(note_tags, Tag.id == note_tags.c.tag_id)
        .where(Tag.user_id == uid)
        .group_by(Tag.name)
        .order_by(func.count(note_tags.c.note_id).desc())
        .limit(10)
    )
    top_tags = [{"name": r.name, "count": r.cnt} for r in top_tags_result.all()]

    # Activity heatmap (last 365 days) — notes created per day
    year_ago = now - timedelta(days=365)
    heatmap_result = await db.execute(
        select(
            func.date_trunc('day', Note.created_at).label("day"),
            func.count(Note.id).label("cnt"),
        )
        .where(Note.user_id == uid, Note.created_at >= year_ago)
        .group_by(func.date_trunc('day', Note.created_at))
        .order_by(func.date_trunc('day', Note.created_at))
    )
    activity_heatmap = [
        {"date": r.day.strftime("%Y-%m-%d"), "count": r.cnt}
        for r in heatmap_result.all()
    ]

    # SR stats
    due_now = (await db.execute(
        select(func.count(FlashCard.id)).where(
            FlashCard.user_id == uid, FlashCard.next_review <= now
        )
    )).scalar() or 0

    mastered = (await db.execute(
        select(func.count(FlashCard.id)).where(
            FlashCard.user_id == uid, FlashCard.interval >= 21
        )
    )).scalar() or 0

    sr_stats = {
        "total_cards": total_flashcards,
        "due_now": due_now,
        "mastered": mastered,
        "learning": total_flashcards - mastered,
    }

    return DashboardResponse(
        total_notes=total_notes,
        total_folders=total_folders,
        total_tags=total_tags,
        total_flashcards=total_flashcards,
        total_words=total_words,
        notes_this_week=notes_this_week,
        notes_this_month=notes_this_month,
        top_folders=top_folders,
        top_tags=top_tags,
        activity_heatmap=activity_heatmap,
        sr_stats=sr_stats,
    )
