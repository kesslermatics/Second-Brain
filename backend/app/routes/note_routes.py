from fastapi import APIRouter, Depends, HTTPException, status, BackgroundTasks
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
from typing import List
from uuid import UUID
from sqlalchemy import or_
from app.database import get_db, async_session
from app.auth import get_current_user
from app.models import User, Note, Folder, Tag, NoteVersion, NoteLink, Image
from app.schemas import NoteCreate, NoteUpdate, NoteResponse, NoteListResponse, TagResponse
from app.services.vector_service import upsert_note_embedding, delete_note_embedding, _vector_search
from app.services.ai_service import suggest_links
import asyncio
import re
import logging

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/notes", tags=["notes"])


async def _auto_link_note(note_id: str, user_id: str, title: str, content: str):
    """Auto-link a note to related notes using vector search + AI."""
    try:
        similar = _vector_search(
            query=f"{title} {content[:500]}",
            user_id=user_id,
            limit=15,
        )
        candidates = [
            {"id": s["note_id"], "title": s["title"], "preview": s["content_preview"]}
            for s in similar
            if s["note_id"] != note_id
        ]
        if not candidates:
            return

        related_ids = await suggest_links(title, content, candidates)

        async with async_session() as db:
            for rid in related_ids:
                existing = await db.execute(
                    select(NoteLink).where(
                        or_(
                            (NoteLink.source_note_id == note_id) & (NoteLink.target_note_id == rid),
                            (NoteLink.source_note_id == rid) & (NoteLink.target_note_id == note_id),
                        )
                    )
                )
                if existing.scalar_one_or_none():
                    continue

                target = await db.get(Note, rid)
                if not target or target.user_id != UUID(user_id):
                    continue

                link = NoteLink(
                    source_note_id=UUID(note_id),
                    target_note_id=target.id,
                    link_type="related",
                    ai_generated=True,
                )
                db.add(link)
            await db.commit()
    except Exception as e:
        logger.error(f"Auto-link failed for note {note_id}: {e}")


async def _enrich_content_with_image_descriptions(content: str, user_id: str) -> str:
    """Replace image references (markdown ![](url) and HTML <img> / attachment links) with AI descriptions for embedding."""
    # Pattern 1: Markdown images ![alt](url)
    md_pattern = re.compile(r'!\[([^\]]*)\]\(([^)]+)\)')
    # Pattern 2: HTML img tags <img src="url" ...>
    img_tag_pattern = re.compile(r'<img[^>]+src="([^"]+)"[^>]*>')
    # Pattern 3: Attachment links with /uploads/ URLs (📎 links)
    attach_pattern = re.compile(r'\[📎\s*([^\]]*)\]\(([^)]+/uploads/[^)]+)\)')
    # Pattern 4: HTML <a> attachment links
    html_attach_pattern = re.compile(r'<a[^>]+href="([^"]*?/uploads/[^"]*?)"[^>]*>📎\s*([^<]*)</a>')

    enriched = content

    # Collect all URLs to look up in one batch
    urls_to_check: list[tuple[str, str, str]] = []  # (full_match, url, alt)

    for alt, url in md_pattern.findall(content):
        urls_to_check.append((f'![{alt}]({url})', url, alt))

    for url in img_tag_pattern.findall(content):
        match = img_tag_pattern.search(content)
        if match:
            urls_to_check.append((match.group(0), url, ''))

    for alt, url in attach_pattern.findall(content):
        urls_to_check.append((f'[📎 {alt}]({url})', url, alt))

    for url, alt in html_attach_pattern.findall(content):
        match_str = f'<a' # will do exact replacement below
        urls_to_check.append(('', url, alt))

    if not urls_to_check:
        return content

    async with async_session() as db:
        for full_match, url, alt_text in urls_to_check:
            if '/uploads/' not in url:
                continue
            filename = url.rsplit('/', 1)[-1] if '/' in url else url
            result = await db.execute(
                select(Image).where(
                    Image.stored_filename == filename,
                    Image.user_id == UUID(user_id),
                )
            )
            img = result.scalar_one_or_none()
            if img and img.description:
                if full_match:
                    enriched = enriched.replace(
                        full_match,
                        f'[Bild: {alt_text or img.original_filename}] {img.description}',
                    )
                else:
                    # HTML <a> tag — find and replace the full tag
                    html_tag = html_attach_pattern.search(enriched)
                    if html_tag:
                        enriched = enriched.replace(
                            html_tag.group(0),
                            f'[Bild: {img.original_filename}] {img.description}',
                        )

    return enriched


def _embed_and_auto_link(
    note_id: str, user_id: str, title: str, content: str, folder_path: str
):
    """Background task: enrich image references with AI descriptions, embed in Qdrant, then auto-link."""
    async def _run():
        enriched = await _enrich_content_with_image_descriptions(content, user_id)
        upsert_note_embedding(note_id, user_id, title, enriched, folder_path)
        await _auto_link_note(note_id, user_id, title, enriched)

    asyncio.run(_run())


@router.get("/", response_model=List[NoteListResponse])
async def list_notes(
    folder_id: UUID = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    query = select(Note).where(Note.user_id == current_user.id)
    if folder_id:
        query = query.where(Note.folder_id == folder_id)
    query = query.order_by(Note.updated_at.desc())
    result = await db.execute(query)
    return result.scalars().all()


@router.get("/{note_id}", response_model=NoteResponse)
async def get_note(
    note_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    note = await db.get(Note, note_id)
    if not note or note.user_id != current_user.id:
        raise HTTPException(status_code=404, detail="Note not found")

    folder = await db.get(Folder, note.folder_id)

    # Load tags
    await db.refresh(note, ["tags"])
    tags = [TagResponse(id=t.id, name=t.name, color=t.color) for t in note.tags]

    return NoteResponse(
        id=note.id,
        title=note.title,
        content=note.content,
        note_type=note.note_type or "text",
        folder_id=note.folder_id,
        folder_path=folder.path if folder else None,
        tags=tags,
        created_at=note.created_at,
        updated_at=note.updated_at,
    )


@router.post("/", response_model=NoteResponse, status_code=status.HTTP_201_CREATED)
async def create_note(
    note: NoteCreate,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    folder = await db.get(Folder, note.folder_id)
    if not folder or folder.user_id != current_user.id:
        raise HTTPException(status_code=404, detail="Folder not found")

    new_note = Note(
        title=note.title,
        content=note.content,
        note_type=note.note_type or "text",
        folder_id=note.folder_id,
        user_id=current_user.id,
    )
    db.add(new_note)
    await db.flush()
    await db.refresh(new_note, ["tags"])

    # Attach tags if provided
    tags = []
    if note.tag_ids:
        for tag_id in note.tag_ids:
            tag = await db.get(Tag, tag_id)
            if tag and tag.user_id == current_user.id:
                new_note.tags.append(tag)
                tags.append(TagResponse(id=tag.id, name=tag.name, color=tag.color))
        await db.flush()

    embed_content = new_note.content
    background_tasks.add_task(
        _embed_and_auto_link,
        note_id=str(new_note.id),
        user_id=str(current_user.id),
        title=new_note.title,
        content=embed_content,
        folder_path=folder.path,
    )

    return NoteResponse(
        id=new_note.id,
        title=new_note.title,
        content=new_note.content,
        note_type=new_note.note_type or "text",
        folder_id=new_note.folder_id,
        folder_path=folder.path,
        tags=tags,
        created_at=new_note.created_at,
        updated_at=new_note.updated_at,
    )


@router.put("/{note_id}", response_model=NoteResponse)
async def update_note(
    note_id: UUID,
    note_update: NoteUpdate,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    note = await db.get(Note, note_id)
    if not note or note.user_id != current_user.id:
        raise HTTPException(status_code=404, detail="Note not found")

    # Save current state as a version before changing
    if note_update.title is not None or note_update.content is not None:
        max_ver_result = await db.execute(
            select(func.coalesce(func.max(NoteVersion.version_number), 0))
            .where(NoteVersion.note_id == note_id)
        )
        next_version = max_ver_result.scalar() + 1
        version = NoteVersion(
            note_id=note_id,
            title=note.title,
            content=note.content,
            version_number=next_version,
        )
        db.add(version)

    if note_update.title is not None:
        note.title = note_update.title
    if note_update.content is not None:
        note.content = note_update.content
    if note_update.note_type is not None:
        note.note_type = note_update.note_type
    if note_update.folder_id is not None:
        folder = await db.get(Folder, note_update.folder_id)
        if not folder or folder.user_id != current_user.id:
            raise HTTPException(status_code=404, detail="Target folder not found")
        note.folder_id = note_update.folder_id

    # Update tags if provided
    if note_update.tag_ids is not None:
        await db.refresh(note, ["tags"])
        note.tags.clear()
        for tag_id in note_update.tag_ids:
            tag = await db.get(Tag, tag_id)
            if tag and tag.user_id == current_user.id:
                note.tags.append(tag)

    await db.flush()
    await db.refresh(note)

    folder = await db.get(Folder, note.folder_id)
    background_tasks.add_task(
        _embed_and_auto_link,
        note_id=str(note.id),
        user_id=str(current_user.id),
        title=note.title,
        content=note.content,
        folder_path=folder.path if folder else "",
    )

    await db.refresh(note, ["tags"])
    tags = [TagResponse(id=t.id, name=t.name, color=t.color) for t in note.tags]

    return NoteResponse(
        id=note.id,
        title=note.title,
        content=note.content,
        note_type=note.note_type or "text",
        folder_id=note.folder_id,
        folder_path=folder.path if folder else None,
        tags=tags,
        created_at=note.created_at,
        updated_at=note.updated_at,
    )


@router.delete("/{note_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_note(
    note_id: UUID,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    note = await db.get(Note, note_id)
    if not note or note.user_id != current_user.id:
        raise HTTPException(status_code=404, detail="Note not found")

    background_tasks.add_task(delete_note_embedding, str(note_id))

    await db.delete(note)
