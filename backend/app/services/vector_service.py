"""OpenAI embeddings and Qdrant-backed hybrid search."""

import asyncio
import logging
from typing import Any

import numpy as np
from openai import OpenAI
from qdrant_client import QdrantClient
from qdrant_client.models import Distance, FieldCondition, Filter, MatchValue, PointStruct, VectorParams
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()

# A separate collection prevents prior-provider and OpenAI vectors from ever being mixed.
# Run ``python reindex_embeddings.py --recreate`` after deployment.
COLLECTION_NAME = "brain_notes_openai"
EMBEDDING_MODEL = settings.OPENAI_EMBEDDING_MODEL
EMBEDDING_DIMENSION = settings.OPENAI_EMBEDDING_DIMENSIONS

_qdrant_client: QdrantClient | None = None
_embedding_client: OpenAI | None = None


def _get_qdrant() -> QdrantClient:
    global _qdrant_client
    if _qdrant_client is None:
        port = None if settings.QDRANT_URL.startswith("https://") else settings.QDRANT_PORT
        _qdrant_client = QdrantClient(url=settings.QDRANT_URL, port=port, timeout=30)
    return _qdrant_client


def _get_embedding_client() -> OpenAI:
    global _embedding_client
    if _embedding_client is None:
        _embedding_client = OpenAI(api_key=settings.OPENAI_API_KEY)
    return _embedding_client


async def ensure_collection() -> None:
    """Create the OpenAI-only collection and reject an incompatible existing one."""
    client = _get_qdrant()
    collections = {collection.name for collection in client.get_collections().collections}
    if COLLECTION_NAME not in collections:
        client.create_collection(
            collection_name=COLLECTION_NAME,
            vectors_config=VectorParams(size=EMBEDDING_DIMENSION, distance=Distance.COSINE),
        )
        logger.info("Created Qdrant collection %s (%s dimensions)", COLLECTION_NAME, EMBEDDING_DIMENSION)
        return

    info = client.get_collection(COLLECTION_NAME)
    vectors = info.config.params.vectors
    size = vectors.size if isinstance(vectors, VectorParams) else None
    if size is not None and size != EMBEDDING_DIMENSION:
        raise RuntimeError(
            f"Qdrant collection '{COLLECTION_NAME}' has {size} dimensions, but "
            f"OPENAI_EMBEDDING_DIMENSIONS is {EMBEDDING_DIMENSION}. "
            "Choose the existing dimension or run reindex_embeddings.py --recreate."
        )


def recreate_collection() -> None:
    """Delete and recreate only the OpenAI collection. Intended for the reindex script."""
    client = _get_qdrant()
    collections = {collection.name for collection in client.get_collections().collections}
    if COLLECTION_NAME in collections:
        client.delete_collection(COLLECTION_NAME)
    client.create_collection(
        collection_name=COLLECTION_NAME,
        vectors_config=VectorParams(size=EMBEDDING_DIMENSION, distance=Distance.COSINE),
    )


def _normalize(vector: list[float]) -> list[float]:
    arr = np.asarray(vector, dtype=np.float32)
    norm = np.linalg.norm(arr)
    return (arr / norm if norm > 0 else arr).tolist()


def _embed(text_value: str) -> list[float]:
    # text-embedding-3-large: hard 8192-token limit.
    # ~4 chars per token → 8000 tokens ≈ 32 000 chars. Stay well below with 20 000.
    text_value = text_value[:20000]
    response = _get_embedding_client().embeddings.create(
        model=EMBEDDING_MODEL,
        input=text_value,
        dimensions=EMBEDDING_DIMENSION,
        encoding_format="float",
    )
    return _normalize(response.data[0].embedding)


def get_embedding(text_value: str) -> list[float]:
    """Create an OpenAI embedding for indexed content."""
    return _embed(text_value)


def get_query_embedding(text_value: str) -> list[float]:
    """Create an OpenAI embedding for a search query in the same vector space."""
    return _embed(text_value)


def upsert_note_embedding(note_id: str, user_id: str, title: str, content: str, folder_path: str) -> None:
    """Embed and upsert a note or file-description payload into the OpenAI collection."""
    vector = get_embedding(f"Title: {title}\nPath: {folder_path}\n\n{content}")
    _get_qdrant().upsert(
        collection_name=COLLECTION_NAME,
        points=[PointStruct(
            id=str(note_id), vector=vector,
            payload={
                "note_id": str(note_id), "user_id": str(user_id), "title": title,
                "folder_path": folder_path, "content_preview": content[:500], "type": "note",
            },
        )],
    )


def delete_note_embedding(note_id: str) -> None:
    try:
        _get_qdrant().delete(collection_name=COLLECTION_NAME, points_selector=[str(note_id)])
    except Exception as exc:
        logger.warning("Could not delete embedding %s: %s", note_id, exc)


def _vector_search(query: str, user_id: str, limit: int = 20) -> list[dict[str, Any]]:
    results = _get_qdrant().query_points(
        collection_name=COLLECTION_NAME,
        query=get_query_embedding(query),
        query_filter=Filter(must=[FieldCondition(key="user_id", match=MatchValue(value=str(user_id)))]),
        limit=limit,
    )
    return [{
        "note_id": point.payload.get("note_id", point.payload.get("image_id", "")),
        "title": point.payload["title"], "folder_path": point.payload["folder_path"],
        "content_preview": point.payload["content_preview"], "score": point.score,
        "type": point.payload.get("type", "note"),
    } for point in results.points]


async def _fulltext_search(query: str, user_id: str, db: AsyncSession, limit: int = 20) -> list[dict]:
    for tsquery_fn in ("websearch_to_tsquery", "plainto_tsquery"):
        sql = text(f"""
            SELECT n.id, n.title, n.content, f.path AS folder_path,
                   ts_rank_cd(setweight(to_tsvector('german', n.title), 'A') ||
                   setweight(to_tsvector('german', n.content), 'B'), {tsquery_fn}('german', :query)) AS rank
            FROM notes n JOIN folders f ON n.folder_id = f.id
            WHERE n.user_id = :user_id AND (setweight(to_tsvector('german', n.title), 'A') ||
              setweight(to_tsvector('german', n.content), 'B')) @@ {tsquery_fn}('german', :query)
            ORDER BY rank DESC LIMIT :limit
        """)
        try:
            rows = (await db.execute(sql, {"query": query, "user_id": str(user_id), "limit": limit})).fetchall()
            if rows:
                return [{"note_id": str(row.id), "title": row.title, "folder_path": row.folder_path,
                         "content_preview": row.content[:500], "score": float(row.rank), "type": "note"} for row in rows]
        except Exception as exc:
            logger.warning("Full-text search (%s) failed: %s", tsquery_fn, exc)
    return []


def _rrf_fuse(vector_results: list[dict], fulltext_results: list[dict], k: int = 60) -> list[dict]:
    scores: dict[str, float] = {}
    metadata: dict[str, dict] = {}
    similarity: dict[str, float] = {}
    for rank, item in enumerate(vector_results):
        key = item["note_id"]
        scores[key] = scores.get(key, 0) + 1 / (k + rank + 1)
        metadata[key], similarity[key] = item, item["score"]
    for rank, item in enumerate(fulltext_results):
        key = item["note_id"]
        scores[key] = scores.get(key, 0) + 1 / (k + rank + 1)
        metadata.setdefault(key, item)
        similarity[key] = min(1.0, similarity[key] + .05) if key in similarity else max(.3, .7 - rank * .05)
    return [{**metadata[key], "score": round(similarity.get(key, .5), 4)}
            for key in sorted(scores, key=scores.get, reverse=True)]


async def hybrid_search(query: str, user_id: str, db: AsyncSession, limit: int = 10) -> list[dict]:
    candidate_limit = max(limit * 2, 20)

    async def vector() -> list[dict]:
        try:
            return await asyncio.to_thread(_vector_search, query, user_id, candidate_limit)
        except Exception as exc:
            logger.error("Vector search failed: %s", exc)
            return []

    vector_results, fulltext_results = await asyncio.gather(vector(), _fulltext_search(query, user_id, db, candidate_limit))
    return _rrf_fuse(vector_results, fulltext_results)[:limit]


def search_similar_notes(query: str, user_id: str, limit: int = 10) -> list[dict]:
    return _vector_search(query, user_id, limit)
