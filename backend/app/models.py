from sqlalchemy import Column, String, Text, DateTime, ForeignKey, Boolean, Integer, Float, Table, UniqueConstraint, JSON
from sqlalchemy.orm import relationship
from sqlalchemy.dialects.postgresql import UUID
import uuid
from datetime import datetime, timezone
from app.database import Base


# ── Many-to-Many: notes <-> tags ──────────────────────────────────────
note_tags = Table(
    "note_tags",
    Base.metadata,
    Column("note_id", UUID(as_uuid=True), ForeignKey("notes.id", ondelete="CASCADE"), primary_key=True),
    Column("tag_id", UUID(as_uuid=True), ForeignKey("tags.id", ondelete="CASCADE"), primary_key=True),
)


class User(Base):
    __tablename__ = "users"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    email = Column(String(255), unique=True, nullable=False, index=True)
    hashed_password = Column(String(255), nullable=False)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))

    folders = relationship("Folder", back_populates="user", cascade="all, delete-orphan")
    notes = relationship("Note", back_populates="user", cascade="all, delete-orphan")
    chat_sessions = relationship("ChatSession", back_populates="user", cascade="all, delete-orphan")
    settings = relationship("UserSettings", back_populates="user", uselist=False, cascade="all, delete-orphan")
    tags = relationship("Tag", back_populates="user", cascade="all, delete-orphan")
    sr_settings = relationship("SRSettings", back_populates="user", uselist=False, cascade="all, delete-orphan")
    images = relationship("Image", back_populates="user", cascade="all, delete-orphan")
    states = relationship("UserState", back_populates="user", cascade="all, delete-orphan")
    courses = relationship("Course", back_populates="user", cascade="all, delete-orphan")


class Folder(Base):
    __tablename__ = "folders"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name = Column(String(255), nullable=False)
    path = Column(String(1024), nullable=False, index=True)
    parent_id = Column(UUID(as_uuid=True), ForeignKey("folders.id", ondelete="CASCADE"), nullable=True)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))

    user = relationship("User", back_populates="folders")
    parent = relationship("Folder", remote_side=[id], back_populates="children")
    children = relationship("Folder", back_populates="parent", cascade="all, delete-orphan", passive_deletes=True)
    notes = relationship("Note", back_populates="folder", cascade="all, delete-orphan")
    images = relationship("Image", back_populates="folder")


class Note(Base):
    __tablename__ = "notes"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    title = Column(String(512), nullable=False)
    content = Column(Text, nullable=False)
    note_type = Column(String(50), nullable=False, default="text")  # "text" or "excalidraw"
    folder_id = Column(UUID(as_uuid=True), ForeignKey("folders.id"), nullable=False)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))

    user = relationship("User", back_populates="notes")
    folder = relationship("Folder", back_populates="notes")
    tags = relationship("Tag", secondary=note_tags, back_populates="notes")
    versions = relationship("NoteVersion", back_populates="note", cascade="all, delete-orphan", order_by="NoteVersion.version_number.desc()")
    outgoing_links = relationship("NoteLink", foreign_keys="NoteLink.source_note_id", back_populates="source_note", cascade="all, delete-orphan")
    incoming_links = relationship("NoteLink", foreign_keys="NoteLink.target_note_id", back_populates="target_note", cascade="all, delete-orphan")
    flashcards = relationship("FlashCard", back_populates="note", cascade="all, delete-orphan")
    images = relationship("Image", back_populates="note")


class ChatSession(Base):
    __tablename__ = "chat_sessions"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    title = Column(String(255), nullable=False, default="New Chat")
    session_type = Column(String(50), nullable=False)  # "notes" or "qa"
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))

    user = relationship("User", back_populates="chat_sessions")
    messages = relationship("ChatMessage", back_populates="session", cascade="all, delete-orphan", order_by="ChatMessage.created_at")


class ChatMessage(Base):
    __tablename__ = "chat_messages"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    session_id = Column(UUID(as_uuid=True), ForeignKey("chat_sessions.id"), nullable=False)
    role = Column(String(50), nullable=False)  # "user" or "assistant"
    content = Column(Text, nullable=False)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))

    session = relationship("ChatSession", back_populates="messages")


class UserSettings(Base):
    __tablename__ = "user_settings"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), unique=True, nullable=False)
    note_prompt = Column(Text, nullable=True)
    qa_prompt = Column(Text, nullable=True)
    edit_prompt = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))

    user = relationship("User", back_populates="settings")


# ── Tags ──────────────────────────────────────────────────────────────
class Tag(Base):
    __tablename__ = "tags"
    __table_args__ = (
        UniqueConstraint("name_lower", "user_id", name="uq_tag_name_user"),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name = Column(String(100), nullable=False)
    name_lower = Column(String(100), nullable=False, index=True)
    color = Column(String(7), nullable=True)  # hex color e.g. #3b82f6
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))

    user = relationship("User", back_populates="tags")
    notes = relationship("Note", secondary=note_tags, back_populates="tags")


# ── Note Version History ──────────────────────────────────────────────
class NoteVersion(Base):
    __tablename__ = "note_versions"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    note_id = Column(UUID(as_uuid=True), ForeignKey("notes.id", ondelete="CASCADE"), nullable=False)
    title = Column(String(512), nullable=False)
    content = Column(Text, nullable=False)
    version_number = Column(Integer, nullable=False)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))

    note = relationship("Note", back_populates="versions")


# ── Note Links (Backlinks / Knowledge Graph) ──────────────────────────
class NoteLink(Base):
    __tablename__ = "note_links"
    __table_args__ = (
        UniqueConstraint("source_note_id", "target_note_id", name="uq_note_link"),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    source_note_id = Column(UUID(as_uuid=True), ForeignKey("notes.id", ondelete="CASCADE"), nullable=False)
    target_note_id = Column(UUID(as_uuid=True), ForeignKey("notes.id", ondelete="CASCADE"), nullable=False)
    link_type = Column(String(50), nullable=False, default="related")  # related, references, extends
    ai_generated = Column(Boolean, default=False)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))

    source_note = relationship("Note", foreign_keys=[source_note_id], back_populates="outgoing_links")
    target_note = relationship("Note", foreign_keys=[target_note_id], back_populates="incoming_links")


# ── Spaced Repetition ─────────────────────────────────────────────────
class FlashCard(Base):
    __tablename__ = "flashcards"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    note_id = Column(UUID(as_uuid=True), ForeignKey("notes.id", ondelete="CASCADE"), nullable=False)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    question = Column(Text, nullable=False)
    answer = Column(Text, nullable=False)
    # SM-2 algorithm fields
    easiness = Column(Float, nullable=False, default=2.5)
    interval = Column(Integer, nullable=False, default=0)  # days
    repetitions = Column(Integer, nullable=False, default=0)
    next_review = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    last_review = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))

    note = relationship("Note", back_populates="flashcards")


class SRSettings(Base):
    """User-level Spaced Repetition settings."""
    __tablename__ = "sr_settings"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), unique=True, nullable=False)
    cards_per_session = Column(Integer, nullable=False, default=20)
    min_easiness = Column(Float, nullable=False, default=1.3)
    max_new_cards_per_day = Column(Integer, nullable=False, default=10)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))

    user = relationship("User", back_populates="sr_settings")


# ── Images ─────────────────────────────────────────────────────────────
class Image(Base):
    """Uploaded image with AI-generated description for RAG."""
    __tablename__ = "images"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    original_filename = Column(String(512), nullable=False)
    stored_filename = Column(String(512), nullable=False)
    content_type = Column(String(100), nullable=False)
    file_size = Column(Integer, nullable=False)
    file_path = Column(String(1024), nullable=False)  # relative path on disk
    description = Column(Text, nullable=True)  # AI-generated description
    folder_id = Column(UUID(as_uuid=True), ForeignKey("folders.id", ondelete="SET NULL"), nullable=True)
    note_id = Column(UUID(as_uuid=True), ForeignKey("notes.id", ondelete="SET NULL"), nullable=True)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    embedded = Column(Boolean, default=False)  # whether description is in Qdrant
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))

    user = relationship("User", back_populates="images")
    folder = relationship("Folder", back_populates="images")
    note = relationship("Note", back_populates="images")


# ── User State (cross-device key-value store) ──────────────────────────
class UserState(Base):
    """Arbitrary per-user key/value state, synced across devices."""
    __tablename__ = "user_states"
    __table_args__ = (
        UniqueConstraint("user_id", "key", name="uq_user_state_key"),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    key = Column(String(255), nullable=False)
    value = Column(Text, nullable=False, default="{}")  # JSON blob
    updated_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))

    user = relationship("User", back_populates="states")


# ── Infinite Teacher ───────────────────────────────────────────────────
class Course(Base):
    """A learning course generated by the Infinite Teacher."""
    __tablename__ = "courses"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    topic = Column(String(512), nullable=False)
    title = Column(String(512), nullable=False)
    description = Column(Text, nullable=True)
    status = Column(String(50), nullable=False, default="draft")  # draft / active / completed
    parent_course_id = Column(UUID(as_uuid=True), ForeignKey("courses.id", ondelete="SET NULL"), nullable=True)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))

    user = relationship("User", back_populates="courses")
    parent_course = relationship("Course", remote_side=[id], backref="child_courses")
    units = relationship("CourseUnit", back_populates="course", cascade="all, delete-orphan", order_by="CourseUnit.order_index")
    messages = relationship("CourseMessage", back_populates="course", cascade="all, delete-orphan", order_by="CourseMessage.created_at")


class CourseUnit(Base):
    """A single lesson/topic within a course."""
    __tablename__ = "course_units"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    course_id = Column(UUID(as_uuid=True), ForeignKey("courses.id", ondelete="CASCADE"), nullable=False)
    unit_number = Column(String(20), nullable=False)
    title = Column(String(512), nullable=False)
    description = Column(Text, nullable=True)
    learning_objectives = Column(JSON, nullable=True)  # ["objective1", "objective2"]
    level = Column(Integer, nullable=False, default=1)
    enabled = Column(Boolean, nullable=False, default=True)
    status = Column(String(50), nullable=False, default="pending")  # pending / active / completed / skipped
    order_index = Column(Integer, nullable=False, default=0)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))

    course = relationship("Course", back_populates="units")
    messages = relationship("CourseMessage", back_populates="unit", cascade="all, delete-orphan", order_by="CourseMessage.created_at")


class CourseMessage(Base):
    """A chat message within a course unit conversation."""
    __tablename__ = "course_messages"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    course_id = Column(UUID(as_uuid=True), ForeignKey("courses.id", ondelete="CASCADE"), nullable=False)
    unit_id = Column(UUID(as_uuid=True), ForeignKey("course_units.id", ondelete="CASCADE"), nullable=True)
    role = Column(String(50), nullable=False)  # "system", "assistant", "user", "note_generated"
    content = Column(Text, nullable=False)
    metadata_ = Column("metadata", JSON, nullable=True)  # e.g. {"note_id": "...", "note_title": "..."}
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))

    course = relationship("Course", back_populates="messages")
    unit = relationship("CourseUnit", back_populates="messages")
