from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, or_
from typing import List
from uuid import UUID
import logging
from app.database import get_db
from app.auth import get_current_user
from app.models import User, Note, NoteLink, Folder
from app.schemas import NoteLinkCreate, NoteLinkResponse, GraphDataResponse
from app.services.ai_service import suggest_links
from app.services.vector_service import _vector_search

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/links", tags=["links"])


@router.get("/note/{note_id}", response_model=List[NoteLinkResponse])
async def get_note_links(
    note_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Get all links for a specific note (both incoming and outgoing)."""
    note = await db.get(Note, note_id)
    if not note or note.user_id != current_user.id:
        raise HTTPException(status_code=404, detail="Note not found")

    result = await db.execute(
        select(NoteLink).where(
            or_(NoteLink.source_note_id == note_id, NoteLink.target_note_id == note_id)
        )
    )
    links = result.scalars().all()

    response = []
    for link in links:
        source = await db.get(Note, link.source_note_id)
        target = await db.get(Note, link.target_note_id)
        response.append(NoteLinkResponse(
            id=link.id,
            source_note_id=link.source_note_id,
            target_note_id=link.target_note_id,
            source_title=source.title if source else None,
            target_title=target.title if target else None,
            link_type=link.link_type,
            ai_generated=link.ai_generated,
            created_at=link.created_at,
        ))

    return response


@router.post("/note/{note_id}", response_model=NoteLinkResponse, status_code=status.HTTP_201_CREATED)
async def create_link(
    note_id: UUID,
    data: NoteLinkCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Manually create a link between two notes."""
    source = await db.get(Note, note_id)
    target = await db.get(Note, data.target_note_id)

    if not source or source.user_id != current_user.id:
        raise HTTPException(status_code=404, detail="Source note not found")
    if not target or target.user_id != current_user.id:
        raise HTTPException(status_code=404, detail="Target note not found")

    # Check if link already exists
    existing = await db.execute(
        select(NoteLink).where(
            NoteLink.source_note_id == note_id,
            NoteLink.target_note_id == data.target_note_id,
        )
    )
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=409, detail="Link already exists")

    link = NoteLink(
        source_note_id=note_id,
        target_note_id=data.target_note_id,
        link_type=data.link_type,
        ai_generated=False,
    )
    db.add(link)
    await db.flush()
    await db.refresh(link)

    return NoteLinkResponse(
        id=link.id,
        source_note_id=link.source_note_id,
        target_note_id=link.target_note_id,
        source_title=source.title,
        target_title=target.title,
        link_type=link.link_type,
        ai_generated=link.ai_generated,
        created_at=link.created_at,
    )


@router.delete("/{link_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_link(
    link_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    link = await db.get(NoteLink, link_id)
    if not link:
        raise HTTPException(status_code=404, detail="Link not found")
    # Verify ownership
    source = await db.get(Note, link.source_note_id)
    if not source or source.user_id != current_user.id:
        raise HTTPException(status_code=404, detail="Link not found")
    await db.delete(link)


@router.post("/note/{note_id}/auto-link")
async def auto_link_note(
    note_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Use AI + vector search to auto-discover and create links for a note."""
    note = await db.get(Note, note_id)
    if not note or note.user_id != current_user.id:
        raise HTTPException(status_code=404, detail="Note not found")

    # Vector search for similar notes
    try:
        similar = _vector_search(
            query=f"{note.title} {note.content[:500]}",
            user_id=str(current_user.id),
            limit=15,
        )
    except Exception as e:
        logger.error(f"Vector search failed for auto-link: {e}")
        return {"created_links": 0, "error": "Vector search timed out, please try again"}

    # Filter out self
    candidates = [
        {"id": s["note_id"], "title": s["title"], "preview": s["content_preview"]}
        for s in similar
        if s["note_id"] != str(note_id)
    ]

    if not candidates:
        return {"created_links": 0}

    # AI selects truly related notes
    try:
        related_ids = await suggest_links(note.title, note.content, candidates)
    except Exception as e:
        logger.error(f"AI suggest_links failed: {e}")
        return {"created_links": 0, "error": "AI suggestion failed, please try again"}

    created = 0
    for rid in related_ids:
        # Check not already linked
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
        if not target or target.user_id != current_user.id:
            continue

        link = NoteLink(
            source_note_id=note_id,
            target_note_id=target.id,
            link_type="related",
            ai_generated=True,
        )
        db.add(link)
        created += 1

    await db.flush()
    return {"created_links": created}


@router.get("/graph", response_model=GraphDataResponse)
async def get_knowledge_graph(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Get all notes and links as graph nodes/edges for knowledge graph visualization."""
    # Get all notes
    notes_result = await db.execute(
        select(Note, Folder.path)
        .join(Folder, Note.folder_id == Folder.id)
        .where(Note.user_id == current_user.id)
    )
    notes_data = notes_result.all()

    nodes = []
    for note, folder_path in notes_data:
        nodes.append({
            "id": str(note.id),
            "title": note.title,
            "folder_path": folder_path,
            "group": folder_path.split("/")[0] if folder_path else "Unsorted",
            "size": min(max(len(note.content) // 200, 3), 15),  # size by content length
        })

    # Get all links
    note_ids = [str(n.id) for n, _ in notes_data]
    links_result = await db.execute(
        select(NoteLink).where(
            NoteLink.source_note_id.in_(note_ids)
        )
    )
    links = links_result.scalars().all()

    edges = [
        {
            "id": str(link.id),
            "source": str(link.source_note_id),
            "target": str(link.target_note_id),
            "type": link.link_type,
            "ai_generated": link.ai_generated,
        }
        for link in links
    ]

    return GraphDataResponse(nodes=nodes, edges=edges)
