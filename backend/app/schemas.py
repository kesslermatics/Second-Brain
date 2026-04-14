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


class NoteUpdate(BaseModel):
    title: Optional[str] = None
    content: Optional[str] = None
    folder_id: Optional[UUID] = None


class NoteResponse(BaseModel):
    id: UUID
    title: str
    content: str
    folder_id: UUID
    folder_path: Optional[str] = None
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class NoteListResponse(BaseModel):
    id: UUID
    title: str
    folder_id: UUID
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


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
