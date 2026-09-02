"""Book processing routes — search, TOC, chapter note generation."""

import json
import asyncio
import uuid
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from sqlalchemy.orm import selectinload
from app.database import get_db
from app.auth import get_current_user
from app.models import User, Folder, Tag, Note, BookDocument
from app.services.book_service import (
    search_book, get_book_toc, generate_chapter_note, generate_topic_note,
    ai_edit_book_content, get_pdf_toc, generate_chapter_note_from_pdf, extract_pdf_text,
    fetch_book_cover,
)
from app.services.book_document_service import document_hash, ingest_book_document, store_document_pdf

router = APIRouter(prefix="/books", tags=["books"])


def _pdf_ingestion_resource(document_id: uuid.UUID) -> str:
    return f"book-document:{document_id}"


def _start_pdf_ingestion_job(document_id: uuid.UUID, user_id: uuid.UUID) -> str:
    """Start a durable ingestion job for an already stored, owned PDF."""
    from app.services.job_store import job_store

    job_id = str(uuid.uuid4())
    job_store.create_job(
        job_id,
        owner_id=str(user_id),
        resource_key=_pdf_ingestion_resource(document_id),
    )

    async def _ingest_events():
        try:
            async for event in ingest_book_document(str(document_id)):
                yield event
        except Exception as exc:
            from app.database import async_session
            async with async_session() as background_db:
                failed = await background_db.get(BookDocument, document_id)
                if failed:
                    failed.status = "failed"
                    failed.error = str(exc)[:500]
                    await background_db.commit()
            raise

    task = asyncio.create_task(job_store.run_job(job_id, _ingest_events()))
    job_store.set_task(job_id, task)
    return job_id


@router.post("/documents/ingest")
async def ingest_pdf_book_document(
    pdf: UploadFile = File(...),
    title: str = Form(...),
    authors: str = Form("[]"),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Persist and asynchronously prepare a PDF as a grounded book source."""
    if not pdf.content_type or "pdf" not in pdf.content_type.lower():
        raise HTTPException(status_code=400, detail="Only PDF files are supported")
    if not title.strip():
        raise HTTPException(status_code=400, detail="Book title required")
    pdf_bytes = await pdf.read()
    if not pdf_bytes:
        raise HTTPException(status_code=400, detail="The uploaded PDF is empty")
    if len(pdf_bytes) > 50 * 1024 * 1024:
        raise HTTPException(status_code=400, detail="PDF too large (max 50 MB)")
    try:
        authors_list = json.loads(authors)
        if not isinstance(authors_list, list):
            authors_list = []
    except Exception:
        authors_list = []

    digest = document_hash(pdf_bytes)
    existing_result = await db.execute(
        select(BookDocument)
        .where(
            BookDocument.user_id == current_user.id,
            BookDocument.content_hash == digest,
        )
        .with_for_update()
    )
    existing = existing_result.scalars().first()
    if existing and existing.status == "ready":
        return {"document_id": str(existing.id), "job_id": None, "reused": True, "status": "ready"}
    if existing:
        # A new upload of the same source is an explicit request to discard a
        # stuck/failed attempt. Cancel the known in-memory job first; after an
        # application restart there is no job to cancel, so reset the orphaned
        # queued/processing record directly.
        from app.services.job_store import job_store

        active_job = job_store.find_active_by_resource(_pdf_ingestion_resource(existing.id))
        if active_job:
            job_store.cancel(active_job.job_id)
            if active_job.task:
                await asyncio.gather(active_job.task, return_exceptions=True)

        existing.original_filename = pdf.filename or existing.original_filename
        existing.stored_path = store_document_pdf(str(current_user.id), str(existing.id), pdf_bytes)
        existing.title = title.strip()
        existing.authors = authors_list
        existing.status = "queued"
        existing.error = None
        existing.page_count = None
        existing.extracted_page_count = None
        existing.toc_source = None
        await db.commit()

        job_id = _start_pdf_ingestion_job(existing.id, current_user.id)
        return {
            "document_id": str(existing.id),
            "job_id": job_id,
            "reused": True,
            "restarted": True,
            "status": "queued",
        }

    document_id = uuid.uuid4()
    stored_path = store_document_pdf(str(current_user.id), str(document_id), pdf_bytes)
    document = BookDocument(
        id=document_id,
        user_id=current_user.id,
        original_filename=pdf.filename or "book.pdf",
        stored_path=stored_path,
        content_hash=digest,
        title=title.strip(),
        authors=authors_list,
        status="queued",
    )
    db.add(document)
    await db.commit()

    job_id = _start_pdf_ingestion_job(document_id, current_user.id)
    return {"document_id": str(document_id), "job_id": job_id, "reused": False, "status": "queued"}


@router.post("/documents/{document_id}/retry")
async def retry_pdf_book_document_ingestion(
    document_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Retry a failed PDF import without re-uploading or duplicating its source."""
    try:
        parsed_document_id = uuid.UUID(document_id)
    except (ValueError, TypeError):
        raise HTTPException(status_code=404, detail="Document not found")

    result = await db.execute(
        select(BookDocument)
        .where(BookDocument.id == parsed_document_id, BookDocument.user_id == current_user.id)
        .with_for_update()
    )
    document = result.scalars().first()
    if not document:
        raise HTTPException(status_code=404, detail="Document not found")
    if document.status in {"queued", "processing"}:
        raise HTTPException(status_code=409, detail="Diese PDF wird bereits vorbereitet.")
    if document.status != "failed":
        raise HTTPException(status_code=409, detail="Nur fehlgeschlagene PDF-Importe können erneut versucht werden.")

    document.status = "queued"
    document.error = None
    await db.commit()
    job_id = _start_pdf_ingestion_job(document.id, current_user.id)
    return {"document_id": str(document.id), "job_id": job_id, "reused": True, "status": "queued"}


@router.get("/documents/{document_id}")
async def get_pdf_book_document(
    document_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    try:
        parsed_document_id = uuid.UUID(document_id)
    except (ValueError, TypeError):
        raise HTTPException(status_code=404, detail="Document not found")

    result = await db.execute(
        select(BookDocument)
        .options(selectinload(BookDocument.chapters))
        .where(BookDocument.id == parsed_document_id, BookDocument.user_id == current_user.id)
    )
    document = result.scalars().first()
    if not document:
        raise HTTPException(status_code=404, detail="Document not found")
    return {
        "id": str(document.id),
        "title": document.title,
        "authors": document.authors or [],
        "status": document.status,
        "error": document.error,
        "page_count": document.page_count,
        "extracted_page_count": document.extracted_page_count,
        "toc_source": document.toc_source,
        "chapters": [
            {
                "id": str(chapter.id),
                "chapter_number": chapter.chapter_number,
                "title": chapter.title,
                "level": chapter.level,
                "start_page": chapter.start_page,
                "end_page": chapter.end_page,
                "ready": bool(chapter.explanation),
            }
            for chapter in document.chapters
        ],
    }


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

    # Load existing note titles for this book to avoid duplicates
    existing_note_titles = []
    book_folder_result = await db.execute(
        select(Folder).where(
            Folder.user_id == current_user.id,
            Folder.path.like(f"Bücher/{book_title}%"),
        )
    )
    book_folders = book_folder_result.scalars().all()
    if book_folders:
        folder_ids = [f.id for f in book_folders]
        notes_result = await db.execute(
            select(Note.title).where(
                Note.folder_id.in_(folder_ids),
                Note.user_id == current_user.id,
            )
        )
        existing_note_titles = [row[0] for row in notes_result.all()]

    result = await generate_chapter_note(
        book_title=book_title,
        authors=authors,
        chapter=chapter,
        folder_structure=folder_structure,
        existing_tags=existing_tag_names,
        existing_note_titles=existing_note_titles,
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


# ── PDF-based endpoints ───────────────────────────────────────────────

@router.post("/pdf-toc")
async def book_pdf_toc(
    pdf: UploadFile = File(...),
    title: str = Form(...),
    authors: str = Form("[]"),
    current_user: User = Depends(get_current_user),
):
    """Extract the table of contents directly from an uploaded PDF only."""
    if not pdf.content_type or "pdf" not in pdf.content_type.lower():
        raise HTTPException(status_code=400, detail="Only PDF files are supported")

    pdf_bytes = await pdf.read()
    if len(pdf_bytes) > 50 * 1024 * 1024:  # 50 MB guard
        raise HTTPException(status_code=400, detail="PDF too large (max 50 MB)")

    try:
        authors_list = json.loads(authors)
    except Exception:
        authors_list = []

    result = await get_pdf_toc(pdf_bytes, title.strip(), authors_list)

    # Fetch a cover image in parallel (best-effort — never blocks TOC delivery)
    try:
        cover_url = await fetch_book_cover(
            title=title.strip(),
            authors=authors_list or None,
        )
        if cover_url:
            result["cover_url"] = cover_url
    except Exception:
        pass  # Cover is optional — don't fail the whole request

    return result


@router.post("/pdf-chapter-note")
async def book_pdf_chapter_note(
    pdf: UploadFile = File(...),
    book_title: str = Form(...),
    authors: str = Form("[]"),
    chapter: str = Form(...),
    all_chapters: str = Form("[]"),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Generate a chapter note using the actual PDF text as the source of truth."""
    if not pdf.content_type or "pdf" not in pdf.content_type.lower():
        raise HTTPException(status_code=400, detail="Only PDF files are supported")

    pdf_bytes = await pdf.read()
    if len(pdf_bytes) > 50 * 1024 * 1024:
        raise HTTPException(status_code=400, detail="PDF too large (max 50 MB)")

    try:
        authors_list = json.loads(authors)
        chapter_dict = json.loads(chapter)
        all_chapters_list = json.loads(all_chapters)
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON in form fields")

    if not book_title.strip() or not chapter_dict:
        raise HTTPException(status_code=400, detail="book_title and chapter required")

    # Extract full text once for this request
    pdf_text = extract_pdf_text(pdf_bytes)

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

    # Existing note titles to avoid duplication
    existing_note_titles = []
    book_folder_result = await db.execute(
        select(Folder).where(
            Folder.user_id == current_user.id,
            Folder.path.like(f"Bücher/{book_title.strip()}%"),
        )
    )
    book_folders = book_folder_result.scalars().all()
    if book_folders:
        folder_ids = [f.id for f in book_folders]
        notes_result = await db.execute(
            select(Note.title).where(
                Note.folder_id.in_(folder_ids),
                Note.user_id == current_user.id,
            )
        )
        existing_note_titles = [row[0] for row in notes_result.all()]

    result = await generate_chapter_note_from_pdf(
        pdf_text=pdf_text,
        book_title=book_title.strip(),
        authors=authors_list,
        chapter=chapter_dict,
        all_chapters=all_chapters_list,
        folder_structure=folder_structure,
        existing_tags=existing_tag_names,
        existing_note_titles=existing_note_titles,
    )

    # Resolve / create tags
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
        "source": "pdf",
    }
