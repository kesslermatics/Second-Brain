from pydantic import BaseModel, EmailStr
from typing import Optional, List
from uuid import UUID
from datetime import datetime


# Auth
class LoginRequest(BaseModel):
    email: str
    password: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"


class UserResponse(BaseModel):
    id: UUID
    email: str
    created_at: datetime

    class Config:
        from_attributes = True


# Tags
class TagCreate(BaseModel):
    name: str
    color: Optional[str] = None


class TagResponse(BaseModel):
    id: UUID
    name: str
    color: Optional[str] = None
    note_count: int = 0

    class Config:
        from_attributes = True


class TagSuggestResponse(BaseModel):
    suggested_tags: List[str]
    existing_matches: List[TagResponse]


# Folders
class FolderCreate(BaseModel):
    name: str
    parent_id: Optional[UUID] = None


class FolderResponse(BaseModel):
    id: UUID
    name: str
    path: str
    parent_id: Optional[UUID] = None
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class FolderTreeResponse(BaseModel):
    id: UUID
    name: str
    path: str
    parent_id: Optional[UUID] = None
    children: List["FolderTreeResponse"] = []
    notes: List["NoteListResponse"] = []

    class Config:
        from_attributes = True


# Notes
class NoteCreate(BaseModel):
    title: str
    content: str
    folder_id: UUID
    note_type: Optional[str] = "text"  # "text" or "excalidraw"
    tag_ids: Optional[List[UUID]] = None


class NoteUpdate(BaseModel):
    title: Optional[str] = None
    content: Optional[str] = None
    folder_id: Optional[UUID] = None
    note_type: Optional[str] = None
    tag_ids: Optional[List[UUID]] = None


class NoteResponse(BaseModel):
    id: UUID
    title: str
    content: str
    note_type: str = "text"
    folder_id: UUID
    folder_path: Optional[str] = None
    tags: List[TagResponse] = []
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class NoteListResponse(BaseModel):
    id: UUID
    title: str
    note_type: str = "text"
    folder_id: UUID
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


# Note Versions
class NoteVersionResponse(BaseModel):
    id: UUID
    note_id: UUID
    title: str
    content: str
    version_number: int
    created_at: datetime

    class Config:
        from_attributes = True


# Note Links
class NoteLinkCreate(BaseModel):
    target_note_id: UUID
    link_type: str = "related"


class NoteLinkResponse(BaseModel):
    id: UUID
    source_note_id: UUID
    target_note_id: UUID
    source_title: Optional[str] = None
    target_title: Optional[str] = None
    link_type: str
    ai_generated: bool
    created_at: datetime

    class Config:
        from_attributes = True


class GraphDataResponse(BaseModel):
    nodes: List[dict]
    edges: List[dict]


# Search
class SearchResultItem(BaseModel):
    note_id: str
    title: str
    folder_path: str
    snippet: str
    score: float
    tags: List[str] = []


class SearchResponse(BaseModel):
    query: str
    results: List[SearchResultItem]
    total: int


# Chat
class ChatSessionCreate(BaseModel):
    title: Optional[str] = "New Chat"
    session_type: str  # "notes" or "qa"


class ChatSessionResponse(BaseModel):
    id: UUID
    title: str
    session_type: str
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class ChatMessageCreate(BaseModel):
    content: str


class ChatMessageResponse(BaseModel):
    id: UUID
    session_id: UUID
    role: str
    content: str
    created_at: datetime

    class Config:
        from_attributes = True


class ChatSessionDetailResponse(BaseModel):
    id: UUID
    title: str
    session_type: str
    messages: List[ChatMessageResponse] = []
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


# AI
class NoteAIRequest(BaseModel):
    content: str


class NoteAIResponse(BaseModel):
    suggested_folder: str
    suggested_title: str
    formatted_content: str


class AIEditRequest(BaseModel):
    note_id: UUID
    instruction: str


class AIEditResponse(BaseModel):
    original_content: str
    suggested_content: str


class RAGQuestionRequest(BaseModel):
    question: str


class RAGAnswerResponse(BaseModel):
    answer: str
    sources: List[dict] = []


FolderTreeResponse.model_rebuild()


# Settings
class SettingsUpdate(BaseModel):
    note_prompt: Optional[str] = None
    qa_prompt: Optional[str] = None
    edit_prompt: Optional[str] = None


class SettingsResponse(BaseModel):
    note_prompt: Optional[str] = None
    qa_prompt: Optional[str] = None
    edit_prompt: Optional[str] = None
    note_prompt_default: str
    qa_prompt_default: str
    edit_prompt_default: str


# Spaced Repetition
class FlashCardResponse(BaseModel):
    id: UUID
    note_id: UUID
    question: str
    answer: str
    easiness: float
    interval: int
    repetitions: int
    next_review: datetime
    last_review: Optional[datetime] = None
    note_title: Optional[str] = None

    class Config:
        from_attributes = True


class FlashCardReview(BaseModel):
    card_id: UUID
    quality: int  # 0-5  (SM-2 scale: 0=forget, 5=perfect)


class SRSettingsUpdate(BaseModel):
    cards_per_session: Optional[int] = None
    min_easiness: Optional[float] = None
    max_new_cards_per_day: Optional[int] = None


class SRSettingsResponse(BaseModel):
    cards_per_session: int = 20
    min_easiness: float = 1.3
    max_new_cards_per_day: int = 10

    class Config:
        from_attributes = True


class ReviewSessionResponse(BaseModel):
    cards: List[FlashCardResponse]
    total_due: int
    new_today: int


# Dashboard / Analytics
class DashboardResponse(BaseModel):
    total_notes: int
    total_folders: int
    total_tags: int
    total_flashcards: int
    total_words: int
    notes_this_week: int
    notes_this_month: int
    top_folders: List[dict]
    top_tags: List[dict]
    activity_heatmap: List[dict]  # [{date: "2026-04-01", count: 3}, ...]
    sr_stats: dict


# Export
class ExportRequest(BaseModel):
    folder_ids: Optional[List[UUID]] = None
    note_ids: Optional[List[UUID]] = None
    include_all: bool = False
    format: str = "markdown"  # "markdown" or "json"


# Summaries
class SummaryRequest(BaseModel):
    scope: str  # "folder", "tag", "all"
    folder_id: Optional[UUID] = None
    tag_name: Optional[str] = None


class SummaryResponse(BaseModel):
    summary: str
    source_count: int
    scope: str


# Images
class ImageResponse(BaseModel):
    id: UUID
    original_filename: str
    stored_filename: str
    content_type: str
    file_size: int
    url: str
    description: Optional[str] = None
    folder_id: Optional[UUID] = None
    note_id: Optional[UUID] = None
    embedded: bool = False
    created_at: datetime

    class Config:
        from_attributes = True


class ImageListResponse(BaseModel):
    images: List[ImageResponse]
    total: int
