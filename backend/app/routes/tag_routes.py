from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
from typing import List
from uuid import UUID
from app.database import get_db
from app.auth import get_current_user
from app.models import User, Tag, Note, note_tags
from app.schemas import TagCreate, TagResponse, TagSuggestResponse
from app.services.ai_service import suggest_tags

router = APIRouter(prefix="/tags", tags=["tags"])


@router.get("", response_model=List[TagResponse])
async def list_tags(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """List all tags for the current user with note counts."""
    result = await db.execute(
        select(Tag, func.count(note_tags.c.note_id).label("note_count"))
        .outerjoin(note_tags, Tag.id == note_tags.c.tag_id)
        .where(Tag.user_id == current_user.id)
        .group_by(Tag.id)
        .order_by(Tag.name)
    )
    rows = result.all()
    return [
        TagResponse(id=tag.id, name=tag.name, color=tag.color, note_count=count)
        for tag, count in rows
    ]


@router.post("", response_model=TagResponse, status_code=status.HTTP_201_CREATED)
async def create_tag(
    data: TagCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Create a new tag (duplicate names per user are rejected)."""
    name_lower = data.name.strip().lower()

    existing = await db.execute(
        select(Tag).where(Tag.user_id == current_user.id, Tag.name_lower == name_lower)
    )
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=409, detail="Tag already exists")

    tag = Tag(
        name=data.name.strip(),
        name_lower=name_lower,
        color=data.color,
        user_id=current_user.id,
    )
    db.add(tag)
    await db.flush()
    await db.refresh(tag)
    await db.commit()
    return TagResponse(id=tag.id, name=tag.name, color=tag.color, note_count=0)


@router.delete("/{tag_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_tag(
    tag_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    tag = await db.get(Tag, tag_id)
    if not tag or tag.user_id != current_user.id:
        raise HTTPException(status_code=404, detail="Tag not found")
    await db.delete(tag)
    await db.commit()


@router.post("/suggest", response_model=TagSuggestResponse)
async def suggest_tags_for_note(
    data: dict,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """AI-suggest tags for a note, accounting for existing tags to avoid duplicates."""
    title = data.get("title", "")
    content = data.get("content", "")

    # Get all existing tag names
    result = await db.execute(
        select(Tag).where(Tag.user_id == current_user.id).order_by(Tag.name)
    )
    all_tags = result.scalars().all()
    existing_names = [t.name for t in all_tags]

    suggested = await suggest_tags(title, content, existing_names)

    # Match suggested tags against existing ones
    existing_matches = []
    new_suggestions = []
    for s in suggested:
        found = False
        for t in all_tags:
            if t.name_lower == s.lower():
                existing_matches.append(
                    TagResponse(id=t.id, name=t.name, color=t.color, note_count=0)
                )
                found = True
                break
        if not found:
            new_suggestions.append(s)

    return TagSuggestResponse(
        suggested_tags=new_suggestions,
        existing_matches=existing_matches,
    )
