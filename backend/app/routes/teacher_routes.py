"""Infinite Teacher routes — course management, interactive teaching, note generation."""

import random
import uuid
import asyncio
from datetime import datetime, timezone
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
from sqlalchemy.orm import selectinload
from app.database import get_db, async_session
from app.auth import get_current_user
from app.models import User, Tag, Course, CourseUnit, CourseMessage
from app.services.teacher_service import (
    generate_curriculum,
    chat_with_teacher,
    generate_lesson_notes,
    generate_term_note,
    generate_advanced_focus,
    ai_edit_lesson_content,
    chat_about_book_chapter,
    generate_book_chapter_notes,
    generate_book_term_note,
)
from app.services.book_service import generate_chapter_summary

router = APIRouter(prefix="/teacher", tags=["teacher"])

TAG_COLORS = ['#3b82f6', '#ef4444', '#10b981', '#f59e0b', '#8b5cf6', '#ec4899', '#06b6d4', '#84cc16']


async def _resolve_tags(suggested_tags: list[str], all_tags: list, current_user, db) -> tuple[list[str], list[str]]:
    """Resolve suggested tag names to IDs, creating new tags if needed."""
    tag_ids = []
    tag_display = []
    for tag_name in suggested_tags:
        tag_lower = tag_name.strip().lower()
        if not tag_lower:
            continue
        found_tag = None
        for t in all_tags:
            if t.name_lower == tag_lower:
                found_tag = t
                break
        if not found_tag:
            found_tag = Tag(
                name=tag_name.strip(),
                name_lower=tag_lower,
                color=random.choice(TAG_COLORS),
                user_id=current_user.id,
            )
            db.add(found_tag)
            await db.flush()
            await db.refresh(found_tag)
            all_tags.append(found_tag)
        tag_ids.append(str(found_tag.id))
        tag_display.append(found_tag.name)
    return tag_ids, tag_display


def _build_previous_units_summary(units: list[CourseUnit], current_order: int) -> str | None:
    """Build a summary string of previously completed units for context."""
    completed = [u for u in units if u.order_index < current_order and u.status == "completed"]
    if not completed:
        return None
    lines = []
    for u in completed:
        lines.append(f"- {u.unit_number} {u.title}")
        if u.learning_objectives:
            for obj in u.learning_objectives:
                lines.append(f"  • {obj}")
    return "\n".join(lines)


def _get_next_unit_title(units: list[CourseUnit], current_order: int) -> str | None:
    """Get the title of the next enabled unit."""
    for u in sorted(units, key=lambda x: x.order_index):
        if u.order_index > current_order and u.enabled and u.status == "pending":
            return u.title
    return None


# ── Course CRUD ───────────────────────────────────────────────────────

@router.get("/courses")
async def list_courses(
    kind: str | None = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """List all courses for the current user, optionally filtered by kind."""
    query = select(Course).where(Course.user_id == current_user.id)
    if kind:
        query = query.where(Course.kind == kind)
    query = query.order_by(Course.updated_at.desc())
    result = await db.execute(query)
    courses = result.scalars().all()

    out = []
    for c in courses:
        # Count units and completed units
        unit_result = await db.execute(
            select(
                func.count(CourseUnit.id).label("total"),
                func.count(CourseUnit.id).filter(CourseUnit.status == "completed").label("completed"),
                func.count(CourseUnit.id).filter(CourseUnit.enabled == True).label("enabled"),
            ).where(CourseUnit.course_id == c.id, CourseUnit.level == 2)
        )
        row = unit_result.one()
        out.append({
            "id": str(c.id),
            "topic": c.topic,
            "title": c.title,
            "description": c.description,
            "status": c.status,
            "kind": c.kind or "teacher",
            "parent_course_id": str(c.parent_course_id) if c.parent_course_id else None,
            "book_authors": c.book_authors,
            "book_year": c.book_year,
            "book_isbn": c.book_isbn,
            "book_publisher": c.book_publisher,
            "total_units": row.total,
            "completed_units": row.completed,
            "enabled_units": row.enabled,
            "created_at": c.created_at.isoformat() if c.created_at else None,
            "updated_at": c.updated_at.isoformat() if c.updated_at else None,
        })
    return out


@router.get("/courses/{course_id}")
async def get_course(
    course_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Get a course with all its units."""
    result = await db.execute(
        select(Course)
        .options(selectinload(Course.units))
        .where(Course.id == course_id, Course.user_id == current_user.id)
    )
    course = result.scalars().first()
    if not course:
        raise HTTPException(status_code=404, detail="Course not found")

    return {
        "id": str(course.id),
        "topic": course.topic,
        "title": course.title,
        "description": course.description,
        "status": course.status,
        "kind": course.kind or "teacher",
        "parent_course_id": str(course.parent_course_id) if course.parent_course_id else None,
        "book_authors": course.book_authors,
        "book_year": course.book_year,
        "book_isbn": course.book_isbn,
        "book_publisher": course.book_publisher,
        "units": [
            {
                "id": str(u.id),
                "unit_number": u.unit_number,
                "title": u.title,
                "description": u.description,
                "learning_objectives": u.learning_objectives or [],
                "level": u.level,
                "enabled": u.enabled,
                "status": u.status,
                "order_index": u.order_index,
                "summary": u.summary,
                "summary_generated_at": u.summary_generated_at.isoformat() if u.summary_generated_at else None,
            }
            for u in sorted(course.units, key=lambda x: x.order_index)
        ],
        "created_at": course.created_at.isoformat() if course.created_at else None,
        "updated_at": course.updated_at.isoformat() if course.updated_at else None,
    }


@router.delete("/courses/{course_id}")
async def delete_course(
    course_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Delete a course and all its units/messages."""
    result = await db.execute(
        select(Course).where(Course.id == course_id, Course.user_id == current_user.id)
    )
    course = result.scalars().first()
    if not course:
        raise HTTPException(status_code=404, detail="Course not found")

    await db.delete(course)
    await db.commit()
    return {"ok": True}


# ── Curriculum Generation ─────────────────────────────────────────────

@router.post("/generate-curriculum")
async def teacher_generate_curriculum(
    data: dict,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Generate a curriculum for a topic and create the course + units in DB."""
    topic = data.get("topic", "").strip()
    parent_course_id = data.get("parent_course_id")
    custom_focus = data.get("custom_focus")

    if not topic:
        raise HTTPException(status_code=400, detail="Topic required")

    # Build parent context if extending a previous course
    parent_context = None
    if parent_course_id:
        parent_result = await db.execute(
            select(Course)
            .options(selectinload(Course.units))
            .where(Course.id == parent_course_id, Course.user_id == current_user.id)
        )
        parent_course = parent_result.scalars().first()
        if parent_course:
            completed = [u for u in parent_course.units if u.status == "completed" and u.level == 2]
            parent_context = f"Kurs: {parent_course.title}\nBehandelte Themen:\n"
            parent_context += "\n".join(f"- {u.title}" for u in completed)

    # Generate curriculum via LLM
    curriculum = await generate_curriculum(topic, parent_context, custom_focus)

    if not curriculum.get("units"):
        raise HTTPException(status_code=500, detail="Konnte keinen Lehrplan generieren")

    # Create course in DB
    course = Course(
        topic=topic,
        title=curriculum["title"],
        description=curriculum.get("description", ""),
        status="draft",
        parent_course_id=parent_course_id,
        user_id=current_user.id,
    )
    db.add(course)
    await db.flush()
    await db.refresh(course)

    # Create units in DB
    for idx, unit_data in enumerate(curriculum["units"]):
        unit = CourseUnit(
            course_id=course.id,
            unit_number=unit_data.get("unit_number", str(idx + 1)),
            title=unit_data.get("title", f"Lektion {idx + 1}"),
            description=unit_data.get("description", ""),
            learning_objectives=unit_data.get("learning_objectives", []),
            level=unit_data.get("level", 1),
            enabled=True,
            status="pending",
            order_index=idx,
        )
        db.add(unit)

    await db.commit()
    await db.refresh(course)

    # Return full course with units
    return await get_course(str(course.id), db, current_user)


# ── Book Course Creation ──────────────────────────────────────────────

@router.post("/create-book-course")
async def create_book_course(
    data: dict,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Create a course from a book's TOC for interactive chapter-by-chapter learning."""
    title = data.get("title", "").strip()
    authors = data.get("authors", [])
    description = data.get("description", "")
    year = data.get("year")
    isbn = data.get("isbn")
    publisher = data.get("publisher")
    chapters = data.get("chapters", [])

    if not title or not chapters:
        raise HTTPException(status_code=400, detail="Title and chapters required")

    # Filter only enabled chapters
    enabled_chapters = [ch for ch in chapters if ch.get("enabled", True)]
    if not enabled_chapters:
        raise HTTPException(status_code=400, detail="At least one chapter must be enabled")

    # Create course
    course = Course(
        topic=title,
        title=title,
        description=description or "",
        status="active",
        kind="book",
        book_authors=authors,
        book_year=str(year) if year else None,
        book_isbn=isbn or None,
        book_publisher=publisher or None,
        user_id=current_user.id,
    )
    db.add(course)
    await db.flush()
    await db.refresh(course)

    # Create units from enabled chapters
    for idx, ch in enumerate(enabled_chapters):
        unit = CourseUnit(
            course_id=course.id,
            unit_number=ch.get("chapter_number", str(idx + 1)),
            title=ch.get("title", f"Kapitel {idx + 1}"),
            description="",
            learning_objectives=[],
            level=ch.get("level", 1),
            enabled=True,
            status="pending",
            order_index=idx,
        )
        db.add(unit)

    await db.commit()
    await db.refresh(course)

    return await get_course(str(course.id), db, current_user)


# ── Unit Management ───────────────────────────────────────────────────

@router.patch("/courses/{course_id}/units/{unit_id}")
async def update_unit(
    course_id: str,
    unit_id: str,
    data: dict,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Update a unit's status or enabled flag."""
    result = await db.execute(
        select(CourseUnit)
        .join(Course)
        .where(
            CourseUnit.id == unit_id,
            CourseUnit.course_id == course_id,
            Course.user_id == current_user.id,
        )
    )
    unit = result.scalars().first()
    if not unit:
        raise HTTPException(status_code=404, detail="Unit not found")

    if "enabled" in data:
        unit.enabled = data["enabled"]
    if "status" in data:
        unit.status = data["status"]

    await db.commit()

    # Auto-generate chapter summary when a book chapter is completed
    if data.get("status") == "completed":
        # Check if this is a book course
        course_result = await db.execute(
            select(Course).where(Course.id == course_id)
        )
        course = course_result.scalars().first()
        if course and (course.kind or "teacher") == "book" and not unit.summary:
            asyncio.create_task(_auto_generate_summary(course_id, unit_id))

    return {"ok": True, "status": unit.status, "enabled": unit.enabled}


@router.patch("/courses/{course_id}/status")
async def update_course_status(
    course_id: str,
    data: dict,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Update course status (draft -> active -> completed)."""
    result = await db.execute(
        select(Course).where(Course.id == course_id, Course.user_id == current_user.id)
    )
    course = result.scalars().first()
    if not course:
        raise HTTPException(status_code=404, detail="Course not found")

    new_status = data.get("status")
    if new_status not in ("draft", "active", "completed"):
        raise HTTPException(status_code=400, detail="Invalid status")

    course.status = new_status
    await db.commit()
    return {"ok": True, "status": course.status}


# ── Unit Chat ─────────────────────────────────────────────────────────

@router.get("/courses/{course_id}/units/{unit_id}/messages")
async def get_unit_messages(
    course_id: str,
    unit_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Get all chat messages for a specific unit."""
    # Validate ownership
    course_result = await db.execute(
        select(Course).where(Course.id == course_id, Course.user_id == current_user.id)
    )
    if not course_result.scalars().first():
        raise HTTPException(status_code=404, detail="Course not found")

    result = await db.execute(
        select(CourseMessage)
        .where(CourseMessage.course_id == course_id, CourseMessage.unit_id == unit_id)
        .order_by(CourseMessage.created_at)
    )
    messages = result.scalars().all()

    return [
        {
            "id": str(m.id),
            "role": m.role,
            "content": m.content,
            "metadata": m.metadata_,
            "created_at": m.created_at.isoformat() if m.created_at else None,
        }
        for m in messages
    ]


@router.post("/courses/{course_id}/units/{unit_id}/chat")
async def unit_chat(
    course_id: str,
    unit_id: str,
    data: dict,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Send a message to the AI teacher for a specific unit."""
    user_message = data.get("message", "").strip()
    if not user_message:
        raise HTTPException(status_code=400, detail="Message required")

    # Load course with units
    course_result = await db.execute(
        select(Course)
        .options(selectinload(Course.units))
        .where(Course.id == course_id, Course.user_id == current_user.id)
    )
    course = course_result.scalars().first()
    if not course:
        raise HTTPException(status_code=404, detail="Course not found")

    # Find the unit
    unit = None
    for u in course.units:
        if str(u.id) == unit_id:
            unit = u
            break
    if not unit:
        raise HTTPException(status_code=404, detail="Unit not found")

    # Get existing chat history for this unit
    msg_result = await db.execute(
        select(CourseMessage)
        .where(CourseMessage.course_id == course_id, CourseMessage.unit_id == unit_id)
        .order_by(CourseMessage.created_at)
    )
    existing_messages = msg_result.scalars().all()
    chat_history = [{"role": m.role, "content": m.content} for m in existing_messages]

    # Build context
    previous_summary = _build_previous_units_summary(list(course.units), unit.order_index)
    next_title = _get_next_unit_title(list(course.units), unit.order_index)

    # Save user message
    user_msg = CourseMessage(
        course_id=course.id,
        unit_id=unit.id,
        role="user",
        content=user_message,
    )
    db.add(user_msg)
    await db.flush()

    # Get AI response — dispatch by course kind
    if (course.kind or "teacher") == "book":
        ai_response = await chat_about_book_chapter(
            book_title=course.title,
            book_authors=course.book_authors or [],
            chapter_number=unit.unit_number,
            chapter_title=unit.title,
            chat_history=chat_history,
            user_message=user_message,
            previous_chapters_summary=previous_summary,
            next_chapter_title=next_title,
        )
    else:
        ai_response = await chat_with_teacher(
            course_title=course.title,
            unit_title=unit.title,
            unit_description=unit.description or "",
            learning_objectives=unit.learning_objectives or [],
            chat_history=chat_history,
            user_message=user_message,
            previous_units_summary=previous_summary,
            next_unit_title=next_title,
        )

    # Save assistant message
    assistant_msg = CourseMessage(
        course_id=course.id,
        unit_id=unit.id,
        role="assistant",
        content=ai_response,
    )
    db.add(assistant_msg)

    # Mark unit as active if first message
    if unit.status == "pending":
        unit.status = "active"

    await db.commit()

    return {
        "message": {
            "id": str(assistant_msg.id),
            "role": "assistant",
            "content": ai_response,
            "created_at": assistant_msg.created_at.isoformat() if assistant_msg.created_at else None,
        }
    }


# ── Note Generation ───────────────────────────────────────────────────

@router.post("/courses/{course_id}/units/{unit_id}/generate-notes")
async def unit_generate_notes(
    course_id: str,
    unit_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Generate atomic notes for the current lesson based on the chat."""
    # Load course + unit
    course_result = await db.execute(
        select(Course)
        .options(selectinload(Course.units))
        .where(Course.id == course_id, Course.user_id == current_user.id)
    )
    course = course_result.scalars().first()
    if not course:
        raise HTTPException(status_code=404, detail="Course not found")

    unit = None
    for u in course.units:
        if str(u.id) == unit_id:
            unit = u
            break
    if not unit:
        raise HTTPException(status_code=404, detail="Unit not found")

    # Get chat history
    msg_result = await db.execute(
        select(CourseMessage)
        .where(CourseMessage.course_id == course_id, CourseMessage.unit_id == unit_id)
        .order_by(CourseMessage.created_at)
    )
    messages = msg_result.scalars().all()
    chat_history = [{"role": m.role, "content": m.content} for m in messages]

    # Get existing tags
    tag_result = await db.execute(
        select(Tag).where(Tag.user_id == current_user.id).order_by(Tag.name)
    )
    all_tags = list(tag_result.scalars().all())
    existing_tag_names = [t.name for t in all_tags]

    # Generate notes — dispatch by course kind
    if (course.kind or "teacher") == "book":
        notes = await generate_book_chapter_notes(
            book_title=course.title,
            book_authors=course.book_authors or [],
            chapter_number=unit.unit_number,
            chapter_title=unit.title,
            chat_history=chat_history,
            existing_tags=existing_tag_names,
        )
    else:
        notes = await generate_lesson_notes(
            course_title=course.title,
            unit_title=unit.title,
            unit_number=unit.unit_number,
            unit_description=unit.description or "",
            learning_objectives=unit.learning_objectives or [],
            chat_history=chat_history,
            existing_tags=existing_tag_names,
        )

    # Resolve tags for each note
    result_notes = []
    for note in notes:
        tag_ids, tag_display = await _resolve_tags(
            note.get("suggested_tags", []), all_tags, current_user, db
        )
        result_notes.append({
            "title": note.get("title", "Untitled"),
            "content": note.get("content", ""),
            "folder": note.get("suggested_folder", f"Kurse/{course.title}"),
            "tag_ids": tag_ids,
            "tag_names": tag_display,
        })

    await db.commit()

    # Record note generation in chat
    note_titles = [n["title"] for n in result_notes]
    gen_msg = CourseMessage(
        course_id=course.id,
        unit_id=unit.id,
        role="note_generated",
        content=f"Notizen generiert: {', '.join(note_titles)}",
        metadata_={"note_titles": note_titles},
    )
    db.add(gen_msg)
    await db.commit()

    return {"notes": result_notes}


@router.post("/courses/{course_id}/units/{unit_id}/generate-term-note")
async def unit_generate_term_note(
    course_id: str,
    unit_id: str,
    data: dict,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Generate a single atomic note for a specific term."""
    term = data.get("term", "").strip()
    if not term:
        raise HTTPException(status_code=400, detail="Term required")

    # Load course + unit
    course_result = await db.execute(
        select(Course)
        .options(selectinload(Course.units))
        .where(Course.id == course_id, Course.user_id == current_user.id)
    )
    course = course_result.scalars().first()
    if not course:
        raise HTTPException(status_code=404, detail="Course not found")

    unit = None
    for u in course.units:
        if str(u.id) == unit_id:
            unit = u
            break
    if not unit:
        raise HTTPException(status_code=404, detail="Unit not found")

    # Get chat history
    msg_result = await db.execute(
        select(CourseMessage)
        .where(CourseMessage.course_id == course_id, CourseMessage.unit_id == unit_id)
        .order_by(CourseMessage.created_at)
    )
    messages = msg_result.scalars().all()
    chat_history = [{"role": m.role, "content": m.content} for m in messages]

    # Get existing tags
    tag_result = await db.execute(
        select(Tag).where(Tag.user_id == current_user.id).order_by(Tag.name)
    )
    all_tags = list(tag_result.scalars().all())
    existing_tag_names = [t.name for t in all_tags]

    # Generate note — dispatch by course kind
    if (course.kind or "teacher") == "book":
        note = await generate_book_term_note(
            term=term,
            book_title=course.title,
            book_authors=course.book_authors or [],
            chapter_title=unit.title,
            chat_history=chat_history,
            existing_tags=existing_tag_names,
        )
    else:
        note = await generate_term_note(
            term=term,
            course_title=course.title,
            unit_title=unit.title,
            chat_history=chat_history,
            existing_tags=existing_tag_names,
        )

    tag_ids, tag_display = await _resolve_tags(
        note.get("suggested_tags", []), all_tags, current_user, db
    )
    await db.commit()

    return {
        "title": note.get("title", term),
        "content": note.get("content", ""),
        "folder": note.get("suggested_folder", f"Kurse/{course.title}"),
        "tag_ids": tag_ids,
        "tag_names": tag_display,
    }


# ── Auto Summary Generation (background task) ────────────────────────

async def _auto_generate_summary(course_id: str, unit_id: str):
    """Background task to auto-generate a chapter summary after completion."""
    try:
        async with async_session() as db:
            course_result = await db.execute(
                select(Course)
                .options(selectinload(Course.units))
                .where(Course.id == course_id)
            )
            course = course_result.scalars().first()
            if not course:
                return

            unit = None
            for u in course.units:
                if str(u.id) == unit_id:
                    unit = u
                    break
            if not unit:
                return

            # Get chat history
            msg_result = await db.execute(
                select(CourseMessage)
                .where(CourseMessage.course_id == course_id, CourseMessage.unit_id == unit_id)
                .order_by(CourseMessage.created_at)
            )
            messages = msg_result.scalars().all()
            chat_history = [{"role": m.role, "content": m.content} for m in messages] if messages else None

            summary_text = await generate_chapter_summary(
                book_title=course.title,
                authors=course.book_authors or [],
                chapter_number=unit.unit_number,
                chapter_title=unit.title,
                chat_history=chat_history,
            )

            unit.summary = summary_text
            unit.summary_generated_at = datetime.now(timezone.utc)
            await db.commit()
    except Exception:
        pass  # Silently fail — user can regenerate manually


# ── AI Edit ───────────────────────────────────────────────────────────

@router.post("/ai-edit-content")
async def teacher_ai_edit_content(
    data: dict,
    current_user: User = Depends(get_current_user),
):
    """AI-edit a lesson note content."""
    content = data.get("content", "").strip()
    instruction = data.get("instruction", "").strip()

    if not content or not instruction:
        raise HTTPException(status_code=400, detail="Content and instruction required")

    new_content = await ai_edit_lesson_content(content, instruction)
    return {"suggested_content": new_content}


# ── Advanced Focus ────────────────────────────────────────────────────

@router.post("/courses/{course_id}/generate-focus")
async def course_generate_focus(
    course_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Generate advanced specialization suggestions for a completed course."""
    result = await db.execute(
        select(Course)
        .options(selectinload(Course.units))
        .where(Course.id == course_id, Course.user_id == current_user.id)
    )
    course = result.scalars().first()
    if not course:
        raise HTTPException(status_code=404, detail="Course not found")

    # Build summary of completed units
    completed = [u for u in course.units if u.status == "completed" and u.level == 2]
    summary_lines = []
    for u in completed:
        summary_lines.append(f"- {u.title}")
        if u.learning_objectives:
            for obj in u.learning_objectives:
                summary_lines.append(f"  • {obj}")
    completed_summary = "\n".join(summary_lines) if summary_lines else "Keine abgeschlossenen Lektionen."

    suggestions = await generate_advanced_focus(
        course_title=course.title,
        course_topic=course.topic,
        completed_units_summary=completed_summary,
    )

    return {"suggestions": suggestions}


# ── Book Chapter Summaries ────────────────────────────────────────────

@router.get("/courses/{course_id}/summaries")
async def get_book_summaries(
    course_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Get all chapter summaries for a book course."""
    result = await db.execute(
        select(Course)
        .options(selectinload(Course.units))
        .where(Course.id == course_id, Course.user_id == current_user.id)
    )
    course = result.scalars().first()
    if not course:
        raise HTTPException(status_code=404, detail="Course not found")

    return {
        "course_id": str(course.id),
        "title": course.title,
        "book_authors": course.book_authors,
        "chapters": [
            {
                "id": str(u.id),
                "unit_number": u.unit_number,
                "title": u.title,
                "level": u.level,
                "status": u.status,
                "summary": u.summary,
                "summary_generated_at": u.summary_generated_at.isoformat() if u.summary_generated_at else None,
                "order_index": u.order_index,
            }
            for u in sorted(course.units, key=lambda x: x.order_index)
            if u.enabled
        ],
    }


@router.post("/courses/{course_id}/units/{unit_id}/generate-summary")
async def unit_generate_summary(
    course_id: str,
    unit_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Generate (or regenerate) a chapter summary for a book unit."""
    # Load course + unit
    result = await db.execute(
        select(Course)
        .options(selectinload(Course.units))
        .where(Course.id == course_id, Course.user_id == current_user.id)
    )
    course = result.scalars().first()
    if not course:
        raise HTTPException(status_code=404, detail="Course not found")

    unit = None
    for u in course.units:
        if str(u.id) == unit_id:
            unit = u
            break
    if not unit:
        raise HTTPException(status_code=404, detail="Unit not found")

    # Get chat history for this unit (if any)
    msg_result = await db.execute(
        select(CourseMessage)
        .where(CourseMessage.course_id == course_id, CourseMessage.unit_id == unit_id)
        .order_by(CourseMessage.created_at)
    )
    messages = msg_result.scalars().all()
    chat_history = [{"role": m.role, "content": m.content} for m in messages] if messages else None

    # Generate summary
    summary_text = await generate_chapter_summary(
        book_title=course.title,
        authors=course.book_authors or [],
        chapter_number=unit.unit_number,
        chapter_title=unit.title,
        chat_history=chat_history,
    )

    # Save to unit
    unit.summary = summary_text
    unit.summary_generated_at = datetime.now(timezone.utc)
    await db.commit()

    return {
        "unit_id": str(unit.id),
        "summary": summary_text,
        "summary_generated_at": unit.summary_generated_at.isoformat(),
    }
