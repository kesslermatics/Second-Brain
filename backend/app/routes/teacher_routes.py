"""Infinite Teacher routes — course management, interactive teaching, note generation."""

import json
import random
import uuid
import asyncio
from datetime import datetime, timezone
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
from sqlalchemy.orm import selectinload
from app.database import get_db, async_session
from app.auth import get_current_user
from app.models import User, Tag, Course, CourseUnit, CourseMessage, Note, Folder
from app.services.teacher_service import (
    generate_curriculum,
    chat_with_teacher,
    chat_with_teacher_stream,
    chat_about_book_chapter,
    chat_about_book_chapter_stream,
    generate_lesson_notes,
    generate_term_note,
    generate_advanced_focus,
    ai_edit_lesson_content,
    generate_book_chapter_notes,
    generate_book_term_note,
    generate_quiz,
    generate_recap,
    generate_lesson_sections,
    get_relevant_knowledge,
    get_existing_note_titles,
    edit_curriculum,
)
from app.services.book_service import generate_chapter_summary
from app.services.teacher_agent import run_teacher_agent

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
            "book_cover_url": c.book_cover_url,
            "category": c.category,
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
        "book_cover_url": course.book_cover_url,
        "category": course.category,
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
                "sections": u.sections or [],
                "current_section": u.current_section or 0,
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
    focus_description = (data.get("focus_description") or "").strip() or None
    num_lessons = data.get("num_lessons")
    try:
        num_lessons = int(num_lessons) if num_lessons else None
        if num_lessons is not None and num_lessons <= 0:
            num_lessons = None
    except (ValueError, TypeError):
        num_lessons = None

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
            ctx_lines = [f"Basiskurs: {parent_course.title}"]
            if parent_course.topic and parent_course.topic != parent_course.title:
                ctx_lines.append(f"Ursprungsthema: {parent_course.topic}")
            if parent_course.description:
                ctx_lines.append(f"Kursbeschreibung: {parent_course.description}")

            # Include ALL lessons (level 2) with their status + objectives, so the
            # deepening builds on the actual curriculum — not just finished lessons.
            lessons = sorted(
                [u for u in parent_course.units if u.level == 2 and u.enabled],
                key=lambda x: x.order_index,
            )
            if lessons:
                ctx_lines.append("\nLehrinhalte des Basiskurses (mit Status):")
                for u in lessons:
                    status_label = {
                        "completed": "abgeschlossen",
                        "active": "begonnen",
                        "skipped": "übersprungen",
                    }.get(u.status, "noch offen")
                    ctx_lines.append(f"- {u.title} [{status_label}]")
                    for obj in (u.learning_objectives or []):
                        ctx_lines.append(f"    • {obj}")

            parent_context = "\n".join(ctx_lines)

    # Generate curriculum via LLM (knowledge-aware: builds on the user's existing notes)
    curriculum = await generate_curriculum(
        topic, parent_context, custom_focus,
        focus_description=focus_description,
        num_lessons=num_lessons,
        user_id=str(current_user.id),
        db=db,
    )

    if not curriculum.get("units"):
        raise HTTPException(status_code=500, detail="Konnte keinen Lehrplan generieren")

    # Create course in DB
    course = Course(
        topic=topic,
        title=curriculum["title"],
        description=curriculum.get("description", ""),
        category=curriculum.get("category"),
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


@router.post("/courses/{course_id}/edit-curriculum")
async def teacher_edit_curriculum(
    course_id: str,
    data: dict,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Revise a draft course's curriculum via a free-text chat instruction.

    Only allowed while the course is still a draft (not yet started). Replaces
    the course's units with the revised set and returns the updated course.
    """
    instruction = (data.get("instruction") or "").strip()
    if not instruction:
        raise HTTPException(status_code=400, detail="Instruction required")

    result = await db.execute(
        select(Course)
        .options(selectinload(Course.units))
        .where(Course.id == course_id, Course.user_id == current_user.id)
    )
    course = result.scalars().first()
    if not course:
        raise HTTPException(status_code=404, detail="Course not found")
    if course.status != "draft":
        raise HTTPException(status_code=400, detail="Nur Entwürfe können angepasst werden")

    # Build the current curriculum shape from the stored units
    current = {
        "title": course.title,
        "description": course.description or "",
        "units": [
            {
                "unit_number": u.unit_number,
                "title": u.title,
                "description": u.description or "",
                "learning_objectives": u.learning_objectives or [],
                "level": u.level,
            }
            for u in sorted(course.units, key=lambda x: x.order_index)
        ],
    }

    revised = await edit_curriculum(current, instruction)
    if not revised.get("units"):
        raise HTTPException(status_code=500, detail="Konnte den Lehrplan nicht anpassen")

    # Replace units
    for u in list(course.units):
        await db.delete(u)
    await db.flush()

    course.title = revised.get("title", course.title)
    course.description = revised.get("description", course.description)
    for idx, unit_data in enumerate(revised["units"]):
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
    cover_url = data.get("cover_url")
    category = data.get("category")
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
        book_cover_url=cover_url or None,
        category=category or None,
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

    # On completion: auto-generate chapter summary (books) + auto-save notes
    if data.get("status") == "completed":
        course_result = await db.execute(
            select(Course).where(Course.id == course_id)
        )
        course = course_result.scalars().first()
        if course and (course.kind or "teacher") == "book" and not unit.summary:
            asyncio.create_task(_auto_generate_summary(course_id, unit_id))
        # Auto-generate + save notes for the finished unit (unless already done),
        # so the student doesn't have to manually save after every step.
        if data.get("auto_notes", True):
            asyncio.create_task(_auto_generate_and_save_notes(course_id, unit_id, str(current_user.id)))

    return {"ok": True, "status": unit.status, "enabled": unit.enabled}


@router.get("/courses/{course_id}/cover-candidates")
async def course_cover_candidates(
    course_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Return several candidate cover image URLs for a book course to choose from."""
    result = await db.execute(
        select(Course).where(Course.id == course_id, Course.user_id == current_user.id)
    )
    course = result.scalars().first()
    if not course:
        raise HTTPException(status_code=404, detail="Course not found")

    from app.services.book_service import fetch_cover_candidates
    candidates = await fetch_cover_candidates(
        title=course.title,
        authors=course.book_authors or [],
        isbn=course.book_isbn,
    )
    return {"candidates": candidates}


@router.patch("/courses/{course_id}/cover")
async def update_course_cover(
    course_id: str,
    data: dict,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Set a book course's cover image URL (chosen from candidates or a custom URL)."""
    result = await db.execute(
        select(Course).where(Course.id == course_id, Course.user_id == current_user.id)
    )
    course = result.scalars().first()
    if not course:
        raise HTTPException(status_code=404, detail="Course not found")

    cover_url = (data.get("cover_url") or "").strip()
    # Basic validation — only allow https image URLs (or clearing the cover).
    if cover_url and not cover_url.startswith("https://"):
        raise HTTPException(status_code=400, detail="Cover-URL muss mit https:// beginnen")

    course.book_cover_url = cover_url or None
    await db.commit()
    return {"ok": True, "cover_url": course.book_cover_url}


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


async def _pregen_all_sections(course_id: str, is_book: bool, course_title: str, book_authors: list | None):
    """Background task: generate sections for all pending lessons in parallel.

    Runs silently after course activation so the first [START] of every lesson
    never needs to wait for a section-generation Flash call.
    Each unit is processed concurrently (up to 8 at a time) to avoid hammering
    the API while still being fast.
    """
    try:
        async with async_session() as db:
            result = await db.execute(
                select(Course)
                .options(selectinload(Course.units))
                .where(Course.id == course_id)
            )
            course = result.scalars().first()
            if not course:
                return

            lessons = [
                u for u in course.units
                if u.level == 2 and u.enabled and not u.sections
            ]
            if not lessons:
                return

            sem = asyncio.Semaphore(8)  # max 8 parallel Flash calls

            async def _gen_one(unit: CourseUnit):
                async with sem:
                    try:
                        sections = await generate_lesson_sections(
                            title=unit.title,
                            description=unit.description or "",
                            learning_objectives=unit.learning_objectives or [],
                            kind="book" if is_book else "lesson",
                            book_title=course_title if is_book else None,
                            book_authors=book_authors if is_book else None,
                        )
                        if sections:
                            unit.sections = sections
                            unit.current_section = 0
                    except Exception:
                        pass  # non-fatal — will be generated on demand

            await asyncio.gather(*[_gen_one(u) for u in lessons])
            await db.commit()
    except Exception as e:
        import logging
        logging.getLogger(__name__).warning("_pregen_all_sections failed: %s", e)


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

    is_book = (course.kind or "teacher") == "book"

    # ── Lesson sections: lazily generate a section plan, then walk through it ──
    # Sections turn one lesson into a guided sequence of steps instead of one wall
    # of text. We generate them on first contact ([START]) and cache on the unit.
    if not unit.sections:
        try:
            unit.sections = await generate_lesson_sections(
                title=unit.title,
                description=unit.description or "",
                learning_objectives=unit.learning_objectives or [],
                kind="book" if is_book else "lesson",
                book_title=course.title if is_book else None,
                book_authors=course.book_authors if is_book else None,
            )
            unit.current_section = 0
        except Exception:
            unit.sections = None

    # Advance to the next section when the student asks to continue
    if user_message == "[ABSCHNITT_WEITER]" and unit.sections:
        if (unit.current_section or 0) < len(unit.sections) - 1:
            unit.current_section = (unit.current_section or 0) + 1

    sections_list = unit.sections or None
    current_section_idx = unit.current_section or 0

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
            sections=sections_list,
            current_section=current_section_idx,
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
            sections=sections_list,
            current_section=current_section_idx,
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

    total_sections = len(sections_list) if sections_list else 0
    is_last_section = total_sections == 0 or current_section_idx >= total_sections - 1

    return {
        "message": {
            "id": str(assistant_msg.id),
            "role": "assistant",
            "content": ai_response,
            "created_at": assistant_msg.created_at.isoformat() if assistant_msg.created_at else None,
        },
        "sections": sections_list or [],
        "current_section": current_section_idx,
        "total_sections": total_sections,
        "is_last_section": is_last_section,
    }


@router.post("/courses/{course_id}/units/{unit_id}/chat/stream")
async def unit_chat_stream(
    course_id: str,
    unit_id: str,
    data: dict,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Start a background teacher-agent job and return a job_id.

    The client immediately gets {"job_id": "..."} and opens
    GET /api/jobs/{job_id}/events to receive the SSE stream.
    Because the job runs as an independent asyncio.Task, the stream
    survives tab switches, phone app changes, and brief network blips —
    the client can reconnect and replay any missed events via ?from=N.
    """
    from app.services.job_store import job_store

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
    existing_messages = msg_result.scalars().all()
    chat_history = [{"role": m.role, "content": m.content} for m in existing_messages]

    # Context
    previous_summary = _build_previous_units_summary(list(course.units), unit.order_index)
    next_title = _get_next_unit_title(list(course.units), unit.order_index)

    # Sections — lazily generate and persist before background task starts
    if not unit.sections:
        try:
            is_book = (course.kind or "teacher") == "book"
            unit.sections = await generate_lesson_sections(
                title=unit.title,
                description=unit.description or "",
                learning_objectives=unit.learning_objectives or [],
                kind="book" if is_book else "lesson",
                book_title=course.title if is_book else None,
                book_authors=course.book_authors if is_book else None,
            )
            unit.current_section = 0
        except Exception:
            unit.sections = None

    if user_message == "[ABSCHNITT_WEITER]" and unit.sections:
        if (unit.current_section or 0) < len(unit.sections) - 1:
            unit.current_section = (unit.current_section or 0) + 1

    sections_list = unit.sections or None
    current_section_idx = unit.current_section or 0

    # Save user message and flush DB state before the background task
    user_msg = CourseMessage(course_id=course.id, unit_id=unit.id, role="user", content=user_message)
    db.add(user_msg)
    await db.flush()

    if unit.status == "pending":
        unit.status = "active"

    await db.commit()

    total_sections = len(sections_list) if sections_list else 0
    is_last_section = total_sections == 0 or current_section_idx >= total_sections - 1

    is_book = (course.kind or "teacher") == "book"
    if is_book:
        authors_str = ", ".join(course.book_authors or []) or "unbekannter Autor"
        subject_block = (
            f'BUCH: "{course.title}" von {authors_str}\n'
            f'KAPITEL {unit.unit_number}: "{unit.title}"'
        )
        if previous_summary:
            subject_block += f"\nBEREITS BEHANDELT:\n{previous_summary}"
        if next_title:
            subject_block += f'\nNÄCHSTES KAPITEL: "{next_title}"'
    else:
        objectives = "\n".join(f"  - {o}" for o in (unit.learning_objectives or []))
        subject_block = (
            f'KURS: "{course.title}"\n'
            f'LEKTION: "{unit.title}"\n{unit.description or ""}\n'
            f'LERNZIELE:\n{objectives}'
        )
        if previous_summary:
            subject_block += f"\nBEREITS BEHANDELT:\n{previous_summary}"
        if next_title:
            subject_block += f'\nNÄCHSTES THEMA: "{next_title}"'

    default_folder = (
        f"Bücher/{course.title}" if is_book else f"Kurse/{course.title}"
    )

    # Snapshot immutable data needed by the background job
    course_id_str = str(course.id)
    unit_id_str = str(unit.id)
    user_id_str = str(current_user.id)

    async def _generate_events():
        """Async generator that drives the agent and yields normalised event dicts."""
        full_response_parts: list[str] = []
        collected_final: dict = {}

        async with async_session() as bg_db:
            async for event in run_teacher_agent(
                user_id=user_id_str,
                db=bg_db,
                subject_block=subject_block,
                sections=sections_list,
                current_section=current_section_idx,
                chat_history=chat_history,
                user_message=user_message,
                default_folder=default_folder,
            ):
                etype = event.get("type")
                if etype == "thinking":
                    yield {"type": "thinking", "content": event["content"]}
                elif etype == "status":
                    yield {"type": "status", "content": event["content"]}
                elif etype == "status_phrases":
                    yield {"type": "status_phrases", "phrases": event["phrases"]}
                elif etype == "chunk":
                    full_response_parts.append(event["content"])
                    yield {"type": "chunk", "content": event["content"]}
                elif etype == "quiz_suggested":
                    yield {"type": "quiz_suggested"}
                elif etype == "knowledge_searched":
                    yield {"type": "knowledge_searched", "count": event.get("count", 0), "top_title": event.get("top_title", ""), "top_score_pct": event.get("top_score_pct", 0), "query": event.get("query", "")}
                elif etype == "quiz_ready":
                    yield {"type": "quiz_ready"}
                elif etype == "note_saved":
                    yield {"type": "note_saved", "note": event["note"]}
                elif etype == "note_read":
                    yield {"type": "note_read", "note_id": event.get("note_id", ""), "title": event.get("title", "")}
                elif etype == "difficulty":
                    yield {"type": "difficulty", "level": event.get("level")}
                elif etype == "understanding":
                    yield {"type": "understanding", "concept": event.get("concept"), "status": event.get("status")}
                elif etype == "checkpoint":
                    yield {"type": "checkpoint", "question": event.get("question", "")}
                elif etype == "diagram":
                    yield {"type": "diagram", "code": event.get("code", ""), "caption": event.get("caption", "")}
                elif etype == "done":
                    collected_final = event

            # Persist the assistant message
            full_text = "".join(full_response_parts).strip()
            quiz_suggested = bool(collected_final.get("quiz_suggested"))
            saved_notes = collected_final.get("saved_notes", [])
            understanding = collected_final.get("understanding", [])
            diagrams = collected_final.get("diagrams", [])
            checkpoints = collected_final.get("checkpoints", [])

            msg_metadata: dict = {}
            if diagrams:
                msg_metadata["diagrams"] = diagrams
            if checkpoints:
                msg_metadata["checkpoints"] = checkpoints
            if understanding:
                msg_metadata["understanding"] = understanding

            assistant_msg = CourseMessage(
                course_id=uuid.UUID(course_id_str),
                unit_id=uuid.UUID(unit_id_str),
                role="assistant",
                content=full_text,
                metadata_=msg_metadata or None,
            )
            bg_db.add(assistant_msg)

            if saved_notes:
                titles = [n.get("title", "") for n in saved_notes if n.get("title")]
                if titles:
                    marker = CourseMessage(
                        course_id=uuid.UUID(course_id_str),
                        unit_id=uuid.UUID(unit_id_str),
                        role="note_generated",
                        content=f"Notizen automatisch gespeichert: {', '.join(titles)}",
                        metadata_={"note_titles": titles, "auto": True},
                    )
                    bg_db.add(marker)

            await bg_db.commit()
            msg_id = str(assistant_msg.id)

        total = len(sections_list) if sections_list else 0
        is_last = total == 0 or current_section_idx >= total - 1

        yield {
            "type": "done",
            "message_id": msg_id,
            "sections": sections_list or [],
            "current_section": current_section_idx,
            "total_sections": total,
            "is_last_section": is_last,
            "quiz_suggested": quiz_suggested,
            "saved_notes": saved_notes,
            "diagrams": diagrams,
            "checkpoints": checkpoints,
            "understanding": understanding,
        }

    # Register job and fire the background task
    job_id = str(uuid.uuid4())
    job_store.create_job(job_id)
    asyncio.create_task(job_store.run_job(job_id, _generate_events()))

    return {"job_id": job_id}


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

    # Only consider conversation that happened AFTER the last note generation,
    # so re-generating notes only covers the newly added content.
    last_marker_idx = -1
    for i, m in enumerate(chat_history):
        if m["role"] == "note_generated":
            last_marker_idx = i
    if last_marker_idx >= 0:
        chat_history = chat_history[last_marker_idx + 1:]

    # Get existing tags
    tag_result = await db.execute(
        select(Tag).where(Tag.user_id == current_user.id).order_by(Tag.name)
    )
    all_tags = list(tag_result.scalars().all())
    existing_tag_names = [t.name for t in all_tags]

    # Load existing note titles for this course/book to avoid duplicates
    # Find the target folder based on course kind
    if (course.kind or "teacher") == "book":
        folder_prefix = f"Bücher/{course.title}"
    else:
        folder_prefix = f"Kurse/{course.title}"

    existing_note_titles = []
    folder_result = await db.execute(
        select(Folder).where(
            Folder.user_id == current_user.id,
            Folder.path.like(f"{folder_prefix}%"),
        )
    )
    course_folders = folder_result.scalars().all()
    if course_folders:
        folder_ids = [f.id for f in course_folders]
        notes_result = await db.execute(
            select(Note.title).where(
                Note.folder_id.in_(folder_ids),
                Note.user_id == current_user.id,
            )
        )
        existing_note_titles = [row[0] for row in notes_result.all()]

    # Cross-course deduplication: also consider semantically related notes from
    # ANYWHERE in the user's brain (not just this course's folder), so overlapping
    # topics across different courses/books don't produce duplicates.
    related_hits = await get_relevant_knowledge(
        f"{unit.title} {unit.description or ''}", str(current_user.id), db, limit=12
    )
    related_titles = [h["title"] for h in related_hits if h.get("title")]
    # Merge, preserving order and uniqueness
    seen = set(existing_note_titles)
    for t in related_titles:
        if t not in seen:
            existing_note_titles.append(t)
            seen.add(t)

    # Generate notes — dispatch by course kind
    if (course.kind or "teacher") == "book":
        notes = await generate_book_chapter_notes(
            book_title=course.title,
            book_authors=course.book_authors or [],
            chapter_number=unit.unit_number,
            chapter_title=unit.title,
            chat_history=chat_history,
            existing_tags=existing_tag_names,
            existing_note_titles=existing_note_titles,
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
            existing_note_titles=existing_note_titles,
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

    # NOTE: We intentionally do NOT record a "note_generated" marker here.
    # This endpoint is also called by background prefetch when a lesson is opened,
    # so recording here would falsely mark notes as created. The marker is only
    # written via the dedicated /record-notes endpoint after an explicit user action.

    return {"notes": result_notes}


@router.post("/courses/{course_id}/units/{unit_id}/record-notes")
async def unit_record_notes(
    course_id: str,
    unit_id: str,
    data: dict,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Record that notes were generated/saved for a unit (explicit user action).

    This writes the 'note_generated' marker into the chat so the teacher knows
    notes exist and future note generation only covers newly added content.
    """
    # Verify the course belongs to the user
    course_result = await db.execute(
        select(Course).where(Course.id == course_id, Course.user_id == current_user.id)
    )
    course = course_result.scalars().first()
    if not course:
        raise HTTPException(status_code=404, detail="Course not found")

    note_titles = data.get("note_titles") or []
    if note_titles:
        content = f"Notizen generiert: {', '.join(note_titles)}"
    else:
        content = "Notizen generiert"

    gen_msg = CourseMessage(
        course_id=course.id,
        unit_id=uuid.UUID(unit_id),
        role="note_generated",
        content=content,
        metadata_={"note_titles": note_titles},
    )
    db.add(gen_msg)
    await db.commit()

    return {"ok": True}


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


async def _load_course_and_unit(course_id: str, unit_id: str, current_user, db):
    """Load a course (with units) and a specific unit, validating ownership."""
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
    return course, unit


@router.post("/courses/{course_id}/units/{unit_id}/quiz")
async def unit_generate_quiz(
    course_id: str,
    unit_id: str,
    data: dict | None = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Generate a short multiple-choice quiz for a lesson / book chapter."""
    course, unit = await _load_course_and_unit(course_id, unit_id, current_user, db)

    # Chat history for context
    msg_result = await db.execute(
        select(CourseMessage)
        .where(CourseMessage.course_id == course_id, CourseMessage.unit_id == unit_id)
        .order_by(CourseMessage.created_at)
    )
    messages = msg_result.scalars().all()
    chat_history = [{"role": m.role, "content": m.content} for m in messages]

    num_questions = 3
    if data and isinstance(data.get("num_questions"), int):
        num_questions = max(1, min(5, data["num_questions"]))

    is_book = (course.kind or "teacher") == "book"
    questions = await generate_quiz(
        title=unit.title,
        description=unit.description or "",
        learning_objectives=unit.learning_objectives or [],
        chat_history=chat_history,
        kind="book" if is_book else "lesson",
        book_title=course.title if is_book else None,
        num_questions=num_questions,
    )

    return {"questions": questions}


@router.post("/courses/{course_id}/units/{unit_id}/recap")
async def unit_generate_recap(
    course_id: str,
    unit_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Generate a short celebratory recap shown when a unit is completed."""
    course, unit = await _load_course_and_unit(course_id, unit_id, current_user, db)

    msg_result = await db.execute(
        select(CourseMessage)
        .where(CourseMessage.course_id == course_id, CourseMessage.unit_id == unit_id)
        .order_by(CourseMessage.created_at)
    )
    messages = msg_result.scalars().all()
    chat_history = [{"role": m.role, "content": m.content} for m in messages]

    next_title = _get_next_unit_title(list(course.units), unit.order_index)
    is_book = (course.kind or "teacher") == "book"

    recap = await generate_recap(
        title=unit.title,
        description=unit.description or "",
        learning_objectives=unit.learning_objectives or [],
        chat_history=chat_history,
        kind="book" if is_book else "lesson",
        book_title=course.title if is_book else None,
        next_title=next_title,
    )

    return recap


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


async def _ensure_folder_path_local(path: str, user_id, db) -> Folder:
    """Create all folders in a path if missing; return the leaf folder."""
    from uuid import UUID as _UUID
    if not path:
        path = "Allgemein"
    uid = user_id if not isinstance(user_id, str) else _UUID(user_id)
    result = await db.execute(select(Folder).where(Folder.path == path, Folder.user_id == uid))
    folder = result.scalar_one_or_none()
    if folder:
        return folder
    parts = path.split("/")
    current_path = ""
    parent_id = None
    for part in parts:
        current_path = f"{current_path}/{part}" if current_path else part
        result = await db.execute(select(Folder).where(Folder.path == current_path, Folder.user_id == uid))
        existing = result.scalar_one_or_none()
        if existing:
            parent_id = existing.id
            folder = existing
            continue
        new_folder = Folder(name=part, path=current_path, parent_id=parent_id, user_id=uid)
        db.add(new_folder)
        await db.flush()
        await db.refresh(new_folder)
        parent_id = new_folder.id
        folder = new_folder
    return folder


async def _auto_generate_and_save_notes(course_id: str, unit_id: str, user_id: str):
    """Background task: generate + save notes for a finished unit automatically.

    Runs on unit completion so the student doesn't have to manually save after
    every step. Skips if notes were already generated for the current context.
    Deduplicates across the whole knowledge base.
    """
    from uuid import UUID as _UUID
    from app.services.vector_service import upsert_note_embedding
    try:
        async with async_session() as db:
            course_result = await db.execute(
                select(Course).options(selectinload(Course.units))
                .where(Course.id == course_id, Course.user_id == _UUID(user_id))
            )
            course = course_result.scalars().first()
            if not course:
                return
            unit = next((u for u in course.units if str(u.id) == unit_id), None)
            if not unit:
                return

            # Chat history for this unit
            msg_result = await db.execute(
                select(CourseMessage)
                .where(CourseMessage.course_id == course_id, CourseMessage.unit_id == unit_id)
                .order_by(CourseMessage.created_at)
            )
            messages = msg_result.scalars().all()
            chat_history = [{"role": m.role, "content": m.content} for m in messages]

            # Skip if notes were already generated after the last real content
            last_marker = -1
            last_content = -1
            for i, m in enumerate(chat_history):
                if m["role"] == "note_generated":
                    last_marker = i
                if m["role"] == "user" and m["content"] not in ("[START]", "[NOTIZEN_ERSTELLT]"):
                    last_content = i
            if last_marker >= 0 and last_marker > last_content:
                return  # already have up-to-date notes

            # Tags
            tag_result = await db.execute(
                select(Tag).where(Tag.user_id == _UUID(user_id)).order_by(Tag.name)
            )
            all_tags = list(tag_result.scalars().all())
            existing_tag_names = [t.name for t in all_tags]

            # Cross-course dedup: related titles from the whole brain
            is_book = (course.kind or "teacher") == "book"
            related_hits = await get_relevant_knowledge(
                f"{unit.title} {unit.description or ''}", user_id, db, limit=12
            )
            existing_note_titles = [h["title"] for h in related_hits if h.get("title")]

            if is_book:
                notes = await generate_book_chapter_notes(
                    book_title=course.title,
                    book_authors=course.book_authors or [],
                    chapter_number=unit.unit_number,
                    chapter_title=unit.title,
                    chat_history=chat_history,
                    existing_tags=existing_tag_names,
                    existing_note_titles=existing_note_titles,
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
                    existing_note_titles=existing_note_titles,
                )

            if not notes:
                return

            async def _resolve_tags_uid(names: list[str]) -> list[Tag]:
                resolved = []
                for tag_name in names or []:
                    tl = tag_name.strip().lower()
                    if not tl:
                        continue
                    found = next((t for t in all_tags if t.name_lower == tl), None)
                    if not found:
                        found = Tag(name=tag_name.strip(), name_lower=tl,
                                    color=random.choice(TAG_COLORS), user_id=_UUID(user_id))
                        db.add(found)
                        await db.flush()
                        await db.refresh(found)
                        all_tags.append(found)
                    resolved.append(found)
                return resolved

            saved_titles = []
            for note in notes:
                tags = await _resolve_tags_uid(note.get("suggested_tags", []))
                folder_path = note.get("suggested_folder") or (
                    f"Bücher/{course.title}" if is_book else f"Kurse/{course.title}"
                )
                folder = await _ensure_folder_path_local(folder_path, user_id, db)
                new_note = Note(
                    title=note.get("title", "Notiz"),
                    content=note.get("content", ""),
                    note_type="text",
                    folder_id=folder.id,
                    user_id=_UUID(user_id),
                )
                db.add(new_note)
                await db.flush()
                await db.refresh(new_note)
                for tag in tags:
                    new_note.tags.append(tag)
                saved_titles.append(new_note.title)
                try:
                    upsert_note_embedding(str(new_note.id), user_id, new_note.title, new_note.content, folder.path)
                except Exception:
                    pass

            # Record a marker so we don't regenerate the same notes again
            marker = CourseMessage(
                course_id=course.id, unit_id=unit.id, role="note_generated",
                content=f"Notizen automatisch generiert: {', '.join(saved_titles)}",
                metadata_={"note_titles": saved_titles, "auto": True},
            )
            db.add(marker)
            await db.commit()
    except Exception:
        pass  # Silently fail — user can still generate notes manually


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
