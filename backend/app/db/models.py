"""SQLAlchemy models for the Phase 1 tables.

Scope note: only the identity and conversation tables exist yet. The RAG, memory, quiz, and
evaluation tables are designed in `db/schema.sql` and are created by the migrations of the phases
that use them (5, 6, 8) — a migration should arrive with the code that reads it, not years early.
"""

import enum
import uuid
from datetime import datetime
from typing import Any

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Computed,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    SmallInteger,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy import false as sa_false
from sqlalchemy import text as sa_text
from sqlalchemy import true as sa_true
from sqlalchemy.dialects.postgresql import CITEXT, JSONB, TSVECTOR, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, created_at_column, uuid_pk


class UserRole(enum.StrEnum):
    STUDENT = "student"
    ADMIN = "admin"


class SessionStatus(enum.StrEnum):
    ACTIVE = "active"
    ENDED = "ended"
    ABANDONED = "abandoned"
    ERROR = "error"


class MessageRole(enum.StrEnum):
    USER = "user"
    ASSISTANT = "assistant"
    SYSTEM = "system"
    TOOL = "tool"


class ToolStatus(enum.StrEnum):
    OK = "ok"
    ERROR = "error"
    REJECTED = "rejected"
    TIMEOUT = "timeout"
    BUDGET_EXCEEDED = "budget_exceeded"


def _pg_enum(py_enum: type[enum.StrEnum], name: str) -> Enum:
    # values_callable keeps the database values equal to the enum *values*, not the member names,
    # so 'student' is stored rather than 'STUDENT'.
    return Enum(
        py_enum, name=name, values_callable=lambda e: [m.value for m in e], native_enum=True
    )


class User(Base):
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = uuid_pk()
    email: Mapped[str] = mapped_column(CITEXT, unique=True, nullable=False)
    password_hash: Mapped[str] = mapped_column(Text, nullable=False)
    role: Mapped[UserRole] = mapped_column(
        _pg_enum(UserRole, "user_role"),
        nullable=False,
        default=UserRole.STUDENT,
        server_default="student",
    )
    is_active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default=sa_true()
    )
    created_at: Mapped[datetime] = created_at_column()
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    student: Mapped["Student | None"] = relationship(
        back_populates="user", uselist=False, cascade="all, delete-orphan"
    )


class RefreshToken(Base):
    __tablename__ = "refresh_tokens"

    id: Mapped[uuid.UUID] = uuid_pk()
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    # Only the hash is stored; a database leak must not yield usable credentials.
    token_hash: Mapped[str] = mapped_column(Text, unique=True, nullable=False)
    # Rotation lineage: every rotation records its parent so a reuse can revoke the whole family.
    family_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    issued_at: Mapped[datetime] = created_at_column()
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    user_agent: Mapped[str | None] = mapped_column(String(256))

    __table_args__ = (
        CheckConstraint("expires_at > issued_at", name="expiry_after_issue"),
        # Partial index: lookups only ever care about tokens that are still live.
        Index(
            "ix_refresh_tokens_user_active",
            "user_id",
            postgresql_where=sa_text("revoked_at IS NULL"),
        ),
        Index("ix_refresh_tokens_family", "family_id"),
    )


class Student(Base):
    __tablename__ = "students"

    id: Mapped[uuid.UUID] = uuid_pk()
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), unique=True, nullable=False
    )
    display_name: Mapped[str] = mapped_column(String(120), nullable=False)
    institution: Mapped[str | None] = mapped_column(String(200))
    semester: Mapped[int | None] = mapped_column(SmallInteger)
    preferred_language: Mapped[str] = mapped_column(
        String(16), nullable=False, default="auto", server_default="auto"
    )
    # Off by default: recording a student's voice requires consent (DATASET.md §5).
    consent_audio_retention: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=sa_false()
    )
    created_at: Mapped[datetime] = created_at_column()
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    user: Mapped[User] = relationship(back_populates="student")

    __table_args__ = (
        CheckConstraint("semester IS NULL OR (semester BETWEEN 1 AND 12)", name="semester_range"),
        CheckConstraint(
            "preferred_language IN ('en','hi','hi-Latn','ta','auto')", name="language_allowed"
        ),
    )


class Session(Base):
    __tablename__ = "sessions"

    id: Mapped[uuid.UUID] = uuid_pk()
    student_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("students.id", ondelete="CASCADE"), nullable=False
    )
    status: Mapped[SessionStatus] = mapped_column(
        _pg_enum(SessionStatus, "session_status"),
        nullable=False,
        default=SessionStatus.ACTIVE,
        server_default="active",
    )
    transport: Mapped[str] = mapped_column(
        String(32), nullable=False, default="websocket", server_default="websocket"
    )
    client_info: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, server_default="{}")
    started_at: Mapped[datetime] = created_at_column()
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    turn_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")

    __table_args__ = (Index("ix_sessions_student_started", "student_id", "started_at"),)


class Message(Base):
    __tablename__ = "messages"

    id: Mapped[uuid.UUID] = uuid_pk()
    session_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("sessions.id", ondelete="CASCADE"), nullable=False
    )
    turn_index: Mapped[int] = mapped_column(Integer, nullable=False)
    seq: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=0, server_default="0")
    role: Mapped[MessageRole] = mapped_column(_pg_enum(MessageRole, "message_role"), nullable=False)
    # For an interrupted assistant turn this holds the SPOKEN prefix only (ARCHITECTURE §5.3).
    content: Mapped[str] = mapped_column(Text, nullable=False)
    unspoken_remainder: Mapped[str | None] = mapped_column(Text)
    language: Mapped[str | None] = mapped_column(String(16))
    stt_confidence: Mapped[float | None] = mapped_column(Numeric(4, 3))
    was_interrupted: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=sa_false()
    )
    spoken_prefix_chars: Mapped[int | None] = mapped_column(Integer)
    audio_ref: Mapped[str | None] = mapped_column(Text)
    token_usage: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    latency_ms: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, server_default="{}")
    created_at: Mapped[datetime] = created_at_column()

    __table_args__ = (
        UniqueConstraint("session_id", "turn_index", "seq", name="uq_messages_turn_seq"),
        CheckConstraint(
            "spoken_prefix_chars IS NULL OR spoken_prefix_chars >= 0",
            name="spoken_prefix_non_negative",
        ),
        # Only an assistant turn can be interrupted; anything else is a bug in the orchestrator.
        CheckConstraint(
            "NOT was_interrupted OR role = 'assistant'", name="interrupted_only_assistant"
        ),
        Index("ix_messages_session_turn", "session_id", "turn_index", "seq"),
    )


class ToolCall(Base):
    __tablename__ = "tool_calls"

    id: Mapped[uuid.UUID] = uuid_pk()
    session_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("sessions.id", ondelete="CASCADE"), nullable=False
    )
    message_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("messages.id", ondelete="CASCADE")
    )
    turn_index: Mapped[int] = mapped_column(Integer, nullable=False)
    tool_name: Mapped[str] = mapped_column(String(64), nullable=False)
    arguments: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    result: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    status: Mapped[ToolStatus] = mapped_column(_pg_enum(ToolStatus, "tool_status"), nullable=False)
    error: Mapped[str | None] = mapped_column(Text)
    duration_ms: Mapped[int | None] = mapped_column(Integer)
    created_at: Mapped[datetime] = created_at_column()

    __table_args__ = (Index("ix_tool_calls_name_status", "tool_name", "status", "created_at"),)


class AuditLog(Base):
    __tablename__ = "audit_log"

    id: Mapped[uuid.UUID] = uuid_pk()
    actor_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )
    action: Mapped[str] = mapped_column(String(64), nullable=False)
    target_type: Mapped[str | None] = mapped_column(String(64))
    target_id: Mapped[str | None] = mapped_column(String(64))
    # Hashed, not raw: an IP address is personal data (SECURITY.md §5).
    ip_hash: Mapped[str | None] = mapped_column(String(64))
    detail: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, server_default="{}")
    created_at: Mapped[datetime] = created_at_column()

    __table_args__ = (Index("ix_audit_log_actor", "actor_id", "created_at"),)


# ---------------------------------------------------------------------------
# RAG corpus (Phase 5)
# ---------------------------------------------------------------------------


class IngestStatus(enum.StrEnum):
    PENDING = "pending"
    PARSING = "parsing"
    EMBEDDING = "embedding"
    READY = "ready"
    FAILED = "failed"


class Document(Base):
    __tablename__ = "documents"

    id: Mapped[uuid.UUID] = uuid_pk()
    title: Mapped[str] = mapped_column(Text, nullable=False)
    subject: Mapped[str] = mapped_column(Text, nullable=False)
    topic: Mapped[str | None] = mapped_column(Text)
    semester: Mapped[int | None] = mapped_column(SmallInteger)
    language: Mapped[str] = mapped_column(
        String(16), nullable=False, default="en", server_default="en"
    )
    source_path: Mapped[str] = mapped_column(Text, nullable=False)
    source_hash: Mapped[str] = mapped_column(Text, unique=True, nullable=False)
    license: Mapped[str | None] = mapped_column(Text)
    page_count: Mapped[int | None] = mapped_column(Integer)
    ingest_status: Mapped[IngestStatus] = mapped_column(
        _pg_enum(IngestStatus, "ingest_status"),
        nullable=False,
        default=IngestStatus.PENDING,
        server_default="pending",
    )
    metadata_: Mapped[dict[str, Any]] = mapped_column(
        "metadata_", JSONB, nullable=False, server_default="{}"
    )
    ingested_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = created_at_column()


class DocumentChunk(Base):
    __tablename__ = "document_chunks"

    id: Mapped[uuid.UUID] = uuid_pk()
    document_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("documents.id", ondelete="CASCADE"), nullable=False
    )
    chunk_index: Mapped[int] = mapped_column(Integer, nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    heading_path: Mapped[str | None] = mapped_column(Text)
    # Generated by Postgres (GENERATED ALWAYS AS ... STORED, see migration 0002). Declared
    # Computed() here too, matching the migration's expression exactly — without it SQLAlchemy
    # includes the column as NULL in every INSERT, which Postgres correctly refuses for a
    # generated column (found by actually running ingestion against real pgvector, not by
    # inspection: the failure is a clean, immediate error, not a silent wrong value).
    content_tsv: Mapped[str | None] = mapped_column(
        TSVECTOR, Computed("to_tsvector('simple', content)", persisted=True), nullable=True
    )
    embedding: Mapped[list[float] | None] = mapped_column(Vector(256))
    embedding_model: Mapped[str | None] = mapped_column(Text)
    token_count: Mapped[int | None] = mapped_column(Integer)
    page_start: Mapped[int | None] = mapped_column(Integer)
    page_end: Mapped[int | None] = mapped_column(Integer)
    section: Mapped[str | None] = mapped_column(Text)
    difficulty: Mapped[str | None] = mapped_column(Text)
    language: Mapped[str | None] = mapped_column(Text)
    metadata_: Mapped[dict[str, Any]] = mapped_column(
        "metadata_", JSONB, nullable=False, server_default="{}"
    )
    created_at: Mapped[datetime] = created_at_column()

    __table_args__ = (
        UniqueConstraint("document_id", "chunk_index", name="uq_document_chunks_doc_chunk"),
        CheckConstraint(
            "difficulty IS NULL OR difficulty IN ('easy','medium','hard')",
            name="ck_document_chunks_difficulty",
        ),
        Index("ix_document_chunks_filter", "language", "difficulty"),
        # These four must mirror migration 0002 exactly, or `alembic check` reports drift — as it
        # did the first time this table was written, before these were declared here (Phase 5
        # audit). SQLAlchemy has no portable HNSW construct, so it is expressed the same way the
        # migration does: a plain Index with postgresql_using/postgresql_ops/postgresql_with.
        Index(
            "ix_document_chunks_embedding",
            "embedding",
            postgresql_using="hnsw",
            postgresql_ops={"embedding": "vector_cosine_ops"},
            postgresql_with={"m": 16, "ef_construction": 64},
        ),
        Index("ix_document_chunks_tsv", "content_tsv", postgresql_using="gin"),
        Index(
            "ix_document_chunks_trgm",
            "content",
            postgresql_using="gin",
            postgresql_ops={"content": "gin_trgm_ops"},
        ),
        Index(
            "ix_document_chunks_meta",
            "metadata_",
            postgresql_using="gin",
            postgresql_ops={"metadata_": "jsonb_path_ops"},
        ),
    )
