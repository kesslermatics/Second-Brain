from qdrant_client import QdrantClient
from qdrant_client.models import Distance, VectorParams, PointStruct, Filter, FieldCondition, MatchValue
import google.generativeai as genai
from app.config import get_settings
import uuid

settings = get_settings()

genai.configure(api_key=settings.GEMINI_API_KEY)

qdrant_client = QdrantClient(
    url=settings.QDRANT_URL,
    port=settings.QDRANT_PORT,
    timeout=30,
)

COLLECTION_NAME = "brain_notes"
EMBEDDING_DIMENSION = 768  # Gemini embedding dimension


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


def get_embedding(text: str) -> list[float]:
    """Get embedding for text using Gemini."""
    result = genai.embed_content(
        model="models/embedding-001",
        content=text,
        task_type="retrieval_document",
    )
    return result["embedding"]


def get_query_embedding(text: str) -> list[float]:
    """Get embedding for a query using Gemini."""
    result = genai.embed_content(
        model="models/embedding-001",
        content=text,
        task_type="retrieval_query",
    )
    return result["embedding"]


def upsert_note_embedding(note_id: str, user_id: str, title: str, content: str, folder_path: str):
    """Upsert a note embedding into Qdrant."""
    text = f"Title: {title}\nPath: {folder_path}\n\n{content}"
    embedding = get_embedding(text)

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


def search_similar_notes(query: str, user_id: str, limit: int = 5) -> list[dict]:
    """Search for similar notes using RAG."""
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
