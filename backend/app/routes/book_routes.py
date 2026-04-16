"""Book processing routes — search, TOC, chapter note generation."""

import json
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.database import get_db
from app.auth import get_current_user
from app.models import User, Folder, Tag
from app.services.book_service import search_book, get_book_toc, generate_chapter_note, generate_topic_note, ai_edit_book_content

router = APIRouter(prefix="/books", tags=["books"])


@router.post("/search")
async def book_search(
    data: dict,
    current_user: User = Depends(get_current_user),
):
    """Search for a book by title/query. Uses Gemini with Google Search grounding."""
    query = data.get("query", "").strip()
    if not query:
        raise HTTPException(status_code=400, detail="Query required")

    result = await search_book(query)
    return result


@router.post("/toc")
async def book_toc(
    data: dict,
    current_user: User = Depends(get_current_user),
):
    """Get the table of contents for a book."""
    title = data.get("title", "").strip()
    authors = data.get("authors", [])
    if not title:
        raise HTTPException(status_code=400, detail="Book title required")

    result = await get_book_toc(title, authors)
    return result


@router.post("/generate-chapter-note")
async def book_generate_chapter_note(
    data: dict,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Generate a note for a specific book chapter."""
    book_title = data.get("book_title", "").strip()
    authors = data.get("authors", [])
    chapter = data.get("chapter", {})

    if not book_title or not chapter:
        raise HTTPException(status_code=400, detail="Book title and chapter required")

    # Get folder structure for context
    folder_result = await db.execute(
        select(Folder).where(Folder.user_id == current_user.id).order_by(Folder.path)
    )
    folders = folder_result.scalars().all()
    folder_structure = [{"path": f.path, "name": f.name} for f in folders]

    # Get existing tags
    tag_result = await db.execute(
        select(Tag).where(Tag.user_id == current_user.id).order_by(Tag.name)
    )
    all_tags = tag_result.scalars().all()
    existing_tag_names = [t.name for t in all_tags]

    result = await generate_chapter_note(
        book_title=book_title,
        authors=authors,
        chapter=chapter,
        folder_structure=folder_structure,
        existing_tags=existing_tag_names,
    )

    # Resolve suggested tags to IDs (create new ones if needed)
    tag_ids = []
    tag_display = []
    for tag_name in result.get("suggested_tags", []):
        tag_lower = tag_name.strip().lower()
        if not tag_lower:
            continue
        found_tag = None
        for t in all_tags:
            if t.name_lower == tag_lower:
                found_tag = t
                break
        if not found_tag:
            import random
            colors = ['#3b82f6', '#ef4444', '#10b981', '#f59e0b', '#8b5cf6', '#ec4899', '#06b6d4', '#84cc16']
            found_tag = Tag(
                name=tag_name.strip(),
                name_lower=tag_lower,
                color=random.choice(colors),
                user_id=current_user.id,
            )
            db.add(found_tag)
            await db.flush()
            await db.refresh(found_tag)
            all_tags.append(found_tag)
        tag_ids.append(str(found_tag.id))
        tag_display.append(found_tag.name)

    await db.commit()

    return {
        "folder": result["suggested_folder"],
        "title": result["suggested_title"],
        "content": result["formatted_content"],
        "tag_ids": tag_ids,
        "tag_names": tag_display,
    }


@router.post("/generate-topic-note")
async def book_generate_topic_note(
    data: dict,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Generate a note for an arbitrary topic in the context of a book."""
    book_title = data.get("book_title", "").strip()
    authors = data.get("authors", [])
    topic = data.get("topic", "").strip()

    if not book_title or not topic:
        raise HTTPException(status_code=400, detail="Book title and topic required")

    # Get existing tags
    tag_result = await db.execute(
        select(Tag).where(Tag.user_id == current_user.id).order_by(Tag.name)
    )
    all_tags = tag_result.scalars().all()
    existing_tag_names = [t.name for t in all_tags]

    result = await generate_topic_note(
        topic=topic,
        book_title=book_title,
        authors=authors,
        existing_tags=existing_tag_names,
    )

    # Resolve suggested tags to IDs (create new ones if needed)
    tag_ids = []
    tag_display = []
    for tag_name in result.get("suggested_tags", []):
        tag_lower = tag_name.strip().lower()
        if not tag_lower:
            continue
        found_tag = None
        for t in all_tags:
            if t.name_lower == tag_lower:
                found_tag = t
                break
        if not found_tag:
            import random
            colors = ['#3b82f6', '#ef4444', '#10b981', '#f59e0b', '#8b5cf6', '#ec4899', '#06b6d4', '#84cc16']
            found_tag = Tag(
                name=tag_name.strip(),
                name_lower=tag_lower,
                color=random.choice(colors),
                user_id=current_user.id,
            )
            db.add(found_tag)
            await db.flush()
            await db.refresh(found_tag)
            all_tags.append(found_tag)
        tag_ids.append(str(found_tag.id))
        tag_display.append(found_tag.name)

    await db.commit()

    return {
        "folder": result["suggested_folder"],
        "title": result["suggested_title"],
        "content": result["formatted_content"],
        "tag_ids": tag_ids,
        "tag_names": tag_display,
    }


@router.post("/ai-edit-content")
async def book_ai_edit_content(
    data: dict,
    current_user: User = Depends(get_current_user),
):
    """AI-edit raw content (no note_id needed, for book preview editing)."""
    content = data.get("content", "").strip()
    instruction = data.get("instruction", "").strip()

    if not content or not instruction:
        raise HTTPException(status_code=400, detail="Content and instruction required")

    new_content = await ai_edit_book_content(content, instruction)
    return {"suggested_content": new_content}
