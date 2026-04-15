from qdrant_client import QdrantClient
from qdrant_client.models import Distance, VectorParams, PointStruct, Filter, FieldCondition, MatchValue
import google.generativeai as genai
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, text, func
from app.config import get_settings
import uuid
import numpy as np
import asyncio
import logging

logger = logging.getLogger(__name__)

settings = get_settings()

COLLECTION_NAME = "brain_notes"
EMBEDDING_DIMENSION = 768
EMBEDDING_MODEL = "models/gemini-embedding-001"

# Lazy initialization — avoid blocking at import time during cold starts
_qdrant_client = None
_genai_configured = False


def _get_qdrant():
    global _qdrant_client
    if _qdrant_client is None:
        url = settings.QDRANT_URL
        # Railway HTTPS proxy handles TLS on port 443 — don't specify port for https URLs
        port = None if url.startswith("https://") else settings.QDRANT_PORT
        _qdrant_client = QdrantClient(
            url=url,
            port=port,
            timeout=30,
        )
    return _qdrant_client


def _ensure_genai():
    global _genai_configured
    if not _genai_configured:
        genai.configure(api_key=settings.GEMINI_API_KEY)
        _genai_configured = True


async def ensure_collection():
    """Ensure the Qdrant collection exists."""
    try:
        client = _get_qdrant()
        collections = client.get_collections().collections
        collection_names = [c.name for c in collections]
        if COLLECTION_NAME not in collection_names:
            client.create_collection(
                collection_name=COLLECTION_NAME,
                vectors_config=VectorParams(
                    size=EMBEDDING_DIMENSION,
                    distance=Distance.COSINE,
                ),
            )
            print(f"Created Qdrant collection: {COLLECTION_NAME}")
        else:
            print(f"Qdrant collection already exists: {COLLECTION_NAME}")
    except Exception as e:
        print(f"Error ensuring Qdrant collection: {e}")


def _normalize(vec: list[float]) -> list[float]:
    """Normalize embedding vector (required for MRL dimensions < 3072)."""
    arr = np.array(vec, dtype=np.float32)
    norm = np.linalg.norm(arr)
    if norm > 0:
        arr = arr / norm
    return arr.tolist()


def get_embedding(text: str) -> list[float]:
    """Get document embedding using gemini-embedding-001."""
    _ensure_genai()
    result = genai.embed_content(
        model=EMBEDDING_MODEL,
        content=text,
        task_type="RETRIEVAL_DOCUMENT",
        output_dimensionality=EMBEDDING_DIMENSION,
    )
    return _normalize(result["embedding"])


def get_query_embedding(text: str) -> list[float]:
    """Get query embedding using gemini-embedding-001."""
    _ensure_genai()
    result = genai.embed_content(
        model=EMBEDDING_MODEL,
        content=text,
        task_type="RETRIEVAL_QUERY",
        output_dimensionality=EMBEDDING_DIMENSION,
    )
    return _normalize(result["embedding"])


def upsert_note_embedding(note_id: str, user_id: str, title: str, content: str, folder_path: str):
    """Upsert a note embedding into Qdrant."""
    embed_text = f"Title: {title}\nPath: {folder_path}\n\n{content}"
    embedding = get_embedding(embed_text)

    point = PointStruct(
        id=str(note_id),
        vector=embedding,
        payload={
            "note_id": str(note_id),
            "user_id": str(user_id),
            "title": title,
            "folder_path": folder_path,
            "content_preview": content[:500],
            "type": "note",
        },
    )
    _get_qdrant().upsert(
        collection_name=COLLECTION_NAME,
        points=[point],
    )


def delete_note_embedding(note_id: str):
    """Delete a note embedding from Qdrant."""
    try:
        _get_qdrant().delete(
            collection_name=COLLECTION_NAME,
            points_selector=[str(note_id)],
        )
    except Exception as e:
        print(f"Error deleting embedding: {e}")


# ---------------------------------------------------------------------------
# Semantic search (Qdrant)
# ---------------------------------------------------------------------------

def _vector_search(query: str, user_id: str, limit: int = 20) -> list[dict]:
    """Search Qdrant for semantically similar notes."""
    query_embedding = get_query_embedding(query)

    results = _get_qdrant().search(
        collection_name=COLLECTION_NAME,
        query_vector=query_embedding,
        query_filter=Filter(
            must=[
                FieldCondition(
                    key="user_id",
                    match=MatchValue(value=str(user_id)),
                )
            ]
        ),
        limit=limit,
    )

    return [
        {
            "note_id": hit.payload.get("note_id", hit.payload.get("image_id", "")),
            "title": hit.payload["title"],
            "folder_path": hit.payload["folder_path"],
            "content_preview": hit.payload["content_preview"],
            "score": hit.score,
            "type": hit.payload.get("type", "note"),
        }
        for hit in results
    ]


# ---------------------------------------------------------------------------
# Full-text search (PostgreSQL ts_rank + websearch_to_tsquery)
# ---------------------------------------------------------------------------

async def _fulltext_search(query: str, user_id: str, db: AsyncSession, limit: int = 20) -> list[dict]:
    """PostgreSQL full-text search over notes (title + content)."""
    from app.models import Note, Folder

    # Try websearch_to_tsquery first, fall back to plainto_tsquery for complex queries
    for tsquery_fn in ['websearch_to_tsquery', 'plainto_tsquery']:
        sql = text(f"""
            SELECT n.id, n.title, n.content, f.path AS folder_path,
                   ts_rank_cd(
                       setweight(to_tsvector('german', n.title), 'A') ||
                       setweight(to_tsvector('german', n.content), 'B'),
                       {tsquery_fn}('german', :query)
                   ) AS rank
            FROM notes n
            JOIN folders f ON n.folder_id = f.id
            WHERE n.user_id = :user_id
              AND (
                  setweight(to_tsvector('german', n.title), 'A') ||
                  setweight(to_tsvector('german', n.content), 'B')
              ) @@ {tsquery_fn}('german', :query)
            ORDER BY rank DESC
            LIMIT :limit
        """)

        try:
            result = await db.execute(sql, {"query": query, "user_id": str(user_id), "limit": limit})
            rows = result.fetchall()
            if rows:
                logger.info(f"Fulltext search ({tsquery_fn}) found {len(rows)} results")
                return [
                    {
                        "note_id": str(row.id),
                        "title": row.title,
                        "folder_path": row.folder_path,
                        "content_preview": row.content[:500],
                        "score": float(row.rank),
                        "type": "note",
                    }
                    for row in rows
                ]
        except Exception as e:
            logger.warning(f"Fulltext search ({tsquery_fn}) failed: {e}")
            continue

    return []


# ---------------------------------------------------------------------------
# Hybrid search with Reciprocal Rank Fusion (RRF)
# ---------------------------------------------------------------------------

def _rrf_fuse(vector_results: list[dict], fulltext_results: list[dict], k: int = 60) -> list[dict]:
    """
    Reciprocal Rank Fusion: merges two ranked lists into one.
    Score = sum( 1 / (k + rank_i) ) for each list the document appears in.
    """
    scores: dict[str, float] = {}
    meta: dict[str, dict] = {}

    for rank, item in enumerate(vector_results):
        nid = item["note_id"]
        scores[nid] = scores.get(nid, 0.0) + 1.0 / (k + rank + 1)
        meta[nid] = item

    for rank, item in enumerate(fulltext_results):
        nid = item["note_id"]
        scores[nid] = scores.get(nid, 0.0) + 1.0 / (k + rank + 1)
        if nid not in meta:
            meta[nid] = item

    sorted_ids = sorted(scores, key=lambda nid: scores[nid], reverse=True)

    return [
        {**meta[nid], "score": round(scores[nid], 6)}
        for nid in sorted_ids
    ]


async def hybrid_search(query: str, user_id: str, db: AsyncSession, limit: int = 10) -> list[dict]:
    """
    Hybrid search: combines Qdrant vector search with PostgreSQL full-text search
    using Reciprocal Rank Fusion (RRF). Returns top `limit` results.
    """
    candidate_limit = max(limit * 2, 20)

    # Run vector search (sync) in thread executor + fulltext search (async) in parallel
    loop = asyncio.get_event_loop()

    async def safe_vector():
        try:
            result = await loop.run_in_executor(None, _vector_search, query, user_id, candidate_limit)
            logger.info(f"Vector search returned {len(result)} results")
            return result
        except Exception as e:
            logger.error(f"Vector search failed: {e}")
            return []

    async def safe_fulltext():
        try:
            result = await _fulltext_search(query, user_id, db, limit=candidate_limit)
            return result
        except Exception as e:
            logger.error(f"Full-text search failed: {e}")
            return []

    vector_results, fulltext_results = await asyncio.gather(safe_vector(), safe_fulltext())

    # Fuse and return top results
    fused = _rrf_fuse(vector_results, fulltext_results)
    logger.info(f"Hybrid search: {len(vector_results)} vector + {len(fulltext_results)} fulltext → {len(fused)} fused results")
    return fused[:limit]


# Keep the old function name as a simple alias for backward compat
def search_similar_notes(query: str, user_id: str, limit: int = 10) -> list[dict]:
    """Vector-only search (sync). Prefer hybrid_search when db session is available."""
    return _vector_search(query, user_id, limit=limit)
