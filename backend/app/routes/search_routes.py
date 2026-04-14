from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.database import get_db
from app.auth import get_current_user
from app.models import User, Note, Tag, note_tags, Image
from app.schemas import SearchResponse, SearchResultItem
from app.services.vector_service import hybrid_search
import re

router = APIRouter(prefix="/search", tags=["search"])


def _make_snippet(content: str, query: str, max_len: int = 250) -> str:
    """Extract a snippet from content around the first query term occurrence, with highlight markers."""
    # Split query into terms
    terms = [t.strip() for t in query.lower().split() if len(t.strip()) > 2]
    content_lower = content.lower()

    best_pos = -1
    for term in terms:
        pos = content_lower.find(term)
        if pos != -1:
            best_pos = pos
            break

    if best_pos == -1:
        snippet = content[:max_len]
    else:
        start = max(0, best_pos - 80)
        snippet = content[start:start + max_len]

    # Wrap matching terms with **bold** markers for frontend
    for term in terms:
        pattern = re.compile(re.escape(term), re.IGNORECASE)
        snippet = pattern.sub(lambda m: f"**{m.group()}**", snippet)

    if not snippet.startswith(content[:5]):
        snippet = "..." + snippet
    if len(snippet) < len(content):
        snippet += "..."

    return snippet


@router.get("", response_model=SearchResponse)
async def search_notes(
    q: str = Query(..., min_length=1, description="Search query"),
    limit: int = Query(20, ge=1, le=50),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Semantic + full-text hybrid search across all notes."""
    results = await hybrid_search(
        query=q,
        user_id=str(current_user.id),
        db=db,
        limit=limit,
    )

    # Enrich results with tags and snippets
    items = []
    for r in results:
        result_type = r.get("type", "note")

        if result_type == "image":
            # Image result — use description as content
            items.append(SearchResultItem(
                note_id=r.get("note_id", ""),
                title=r["title"],
                folder_path=r["folder_path"],
                snippet=r.get("content_preview", "")[:250],
                score=r["score"],
                tags=["📷 Bild"],
            ))
            continue

        # Note result — get full content for snippet
        note = await db.get(Note, r["note_id"])
        content = note.content if note else r.get("content_preview", "")

        # Get tags for this note
        tag_result = await db.execute(
            select(Tag.name)
            .join(note_tags, Tag.id == note_tags.c.tag_id)
            .where(note_tags.c.note_id == r["note_id"])
        )
        tag_names = [row[0] for row in tag_result.all()]

        items.append(SearchResultItem(
            note_id=r["note_id"],
            title=r["title"],
            folder_path=r["folder_path"],
            snippet=_make_snippet(content, q),
            score=r["score"],
            tags=tag_names,
        ))

    return SearchResponse(
        query=q,
        results=items,
        total=len(items),
    )
