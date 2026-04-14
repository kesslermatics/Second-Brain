from qdrant_client import QdrantClient
from qdrant_client.models import Distance, VectorParams, PointStruct, Filter, FieldCondition, MatchValue
import google.generativeai as genai
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, text, func
from app.config import get_settings
import uuid
import numpy as np

settings = get_settings()

genai.configure(api_key=settings.GEMINI_API_KEY)

qdrant_client = QdrantClient(
    url=settings.QDRANT_URL,
    port=settings.QDRANT_PORT,
    timeout=30,
)

COLLECTION_NAME = "brain_notes"
EMBEDDING_DIMENSION = 768
EMBEDDING_MODEL = "models/gemini-embedding-001"


async def ensure_collection():
    """Ensure the Qdrant collection exists."""
    try:
        collections = qdrant_client.get_collections().collections
        collection_names = [c.name for c in collections]
        if COLLECTION_NAME not in collection_names:
            qdrant_client.create_collection(
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
    result = genai.embed_content(
        model=EMBEDDING_MODEL,
        content=text,
        task_type="RETRIEVAL_DOCUMENT",
        output_dimensionality=EMBEDDING_DIMENSION,
    )
    return _normalize(result["embedding"])


def get_query_embedding(text: str) -> list[float]:
    """Get query embedding using gemini-embedding-001."""
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
        },
    )
    qdrant_client.upsert(
        collection_name=COLLECTION_NAME,
        points=[point],
    )


def delete_note_embedding(note_id: str):
    """Delete a note embedding from Qdrant."""
    try:
        qdrant_client.delete(
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

    results = qdrant_client.search(
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
            "note_id": hit.payload["note_id"],
            "title": hit.payload["title"],
            "folder_path": hit.payload["folder_path"],
            "content_preview": hit.payload["content_preview"],
            "score": hit.score,
        }
        for hit in results
    ]


# ---------------------------------------------------------------------------
# Full-text search (PostgreSQL ts_rank + websearch_to_tsquery)
# ---------------------------------------------------------------------------

async def _fulltext_search(query: str, user_id: str, db: AsyncSession, limit: int = 20) -> list[dict]:
    """PostgreSQL full-text search over notes (title + content)."""
    # Import here to avoid circular imports
    from app.models import Note, Folder

    sql = text("""
        SELECT n.id, n.title, n.content, f.path AS folder_path,
               ts_rank_cd(
                   setweight(to_tsvector('german', n.title), 'A') ||
                   setweight(to_tsvector('german', n.content), 'B'),
                   websearch_to_tsquery('german', :query)
               ) AS rank
        FROM notes n
        JOIN folders f ON n.folder_id = f.id
        WHERE n.user_id = :user_id
          AND (
              setweight(to_tsvector('german', n.title), 'A') ||
              setweight(to_tsvector('german', n.content), 'B')
          ) @@ websearch_to_tsquery('german', :query)
        ORDER BY rank DESC
        LIMIT :limit
    """)

    result = await db.execute(sql, {"query": query, "user_id": str(user_id), "limit": limit})
    rows = result.fetchall()

    return [
        {
            "note_id": str(row.id),
            "title": row.title,
            "folder_path": row.folder_path,
            "content_preview": row.content[:500],
            "score": float(row.rank),
        }
        for row in rows
    ]


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
    # Fetch more candidates from each source, then fuse
    candidate_limit = max(limit * 2, 20)

    # Vector search
    try:
        vector_results = _vector_search(query, user_id, limit=candidate_limit)
    except Exception as e:
        print(f"Vector search failed: {e}")
        vector_results = []

    # Full-text search
    try:
        fulltext_results = await _fulltext_search(query, user_id, db, limit=candidate_limit)
    except Exception as e:
        print(f"Full-text search failed: {e}")
        fulltext_results = []

    # Fuse and return top results
    fused = _rrf_fuse(vector_results, fulltext_results)
    return fused[:limit]


# Keep the old function name as a simple alias for backward compat
def search_similar_notes(query: str, user_id: str, limit: int = 10) -> list[dict]:
    """Vector-only search (sync). Prefer hybrid_search when db session is available."""
    return _vector_search(query, user_id, limit=limit)
