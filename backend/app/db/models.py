"""SQLAlchemy models, added phase by phase as the code that reads them arrives.

Identity and conversation tables: Phase 1. RAG corpus: Phase 5. Agent tools, memory, study plans
and quizzes: Phase 6. All are designed in `db/schema.sql`; the evaluation and experiment tables
there remain undeployed until Phase 8 needs them — a migration should arrive with the code that
reads it, not years early.
"""

import enum
import uuid
from datetime import date, datetime
from typing import Any

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    ARRAY,
    Boolean,
    CheckConstraint,
    Computed,
    Date,
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


# ---------------------------------------------------------------------------
# Agent tools, memory, study plans and quizzes (Phase 6)
# ---------------------------------------------------------------------------


class PlanStatus(enum.StrEnum):
    ACTIVE = "active"
    COMPLETED = "completed"
    ABANDONED = "abandoned"


class MemoryKind(enum.StrEnum):
    OBSERVATION = "observation"
    PROFILE_UPDATE = "profile_update"
    TOPIC_UPDATE = "topic_update"


class RetrievalLog(Base):
    """One row per `search_knowledge` call — every retrieval this system ever performs, traceable
    to the config that produced it (ARCHITECTURE §11), independent of the Phase 5 eval suite's own
    offline runs. Did not exist before Phase 6 because nothing called the RAG pipeline with a real
    session/message to attribute it to until the tool-execution loop did."""

    __tablename__ = "retrieval_logs"

    id: Mapped[uuid.UUID] = uuid_pk()
    session_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("sessions.id", ondelete="CASCADE")
    )
    message_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("messages.id", ondelete="CASCADE")
    )
    query: Mapped[str] = mapped_column(Text, nullable=False)
    query_language: Mapped[str | None] = mapped_column(Text)
    retriever_config: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    candidate_ids: Mapped[list[uuid.UUID]] = mapped_column(
        ARRAY(UUID(as_uuid=True)), nullable=False, server_default="{}"
    )
    chosen_ids: Mapped[list[uuid.UUID]] = mapped_column(
        ARRAY(UUID(as_uuid=True)), nullable=False, server_default="{}"
    )
    scores: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    latency_ms: Mapped[int | None] = mapped_column(Integer)
    created_at: Mapped[datetime] = created_at_column()

    __table_args__ = (Index("ix_retrieval_logs_session", "session_id", "created_at"),)


class StudentProfile(Base):
    __tablename__ = "student_profiles"

    id: Mapped[uuid.UUID] = uuid_pk()
    student_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("students.id", ondelete="CASCADE"),
        unique=True,
        nullable=False,
    )
    digest: Mapped[str] = mapped_column(Text, nullable=False, default="", server_default="")
    learning_preferences: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default="{}"
    )
    explanation_style: Mapped[str | None] = mapped_column(Text)
    # Bumped on every applied change (DATA_MODEL §4) — lets a client detect a stale read without
    # a second round trip, and gives `memory_events` something concrete to point back at.
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1, server_default="1")
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class StudentTopic(Base):
    __tablename__ = "student_topics"

    id: Mapped[uuid.UUID] = uuid_pk()
    student_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("students.id", ondelete="CASCADE"), nullable=False
    )
    subject: Mapped[str] = mapped_column(Text, nullable=False)
    topic: Mapped[str] = mapped_column(Text, nullable=False)
    # EWMA-updated, never replaced (ARCHITECTURE §12) — a mastery estimate, not knowledge tracing.
    mastery: Mapped[float] = mapped_column(
        Numeric(4, 3), nullable=False, default=0.5, server_default="0.500"
    )
    # How much evidence backs `mastery`, distinct from the estimate itself — a fresh topic starts
    # low-confidence, not "known to be average".
    confidence: Mapped[float] = mapped_column(
        Numeric(4, 3), nullable=False, default=0.1, server_default="0.100"
    )
    evidence_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    last_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    __table_args__ = (
        UniqueConstraint(
            "student_id", "subject", "topic", name="uq_student_topics_student_subject_topic"
        ),
        CheckConstraint("mastery BETWEEN 0 AND 1", name="ck_student_topics_mastery_range"),
        CheckConstraint("confidence BETWEEN 0 AND 1", name="ck_student_topics_confidence_range"),
        # Partial index: the only query this table exists to answer fast is "what is this student
        # weak at" (DATA_MODEL §4) — get_student_progress's most common shape.
        Index(
            "ix_student_topics_weak",
            "student_id",
            "mastery",
            postgresql_where=sa_text("mastery < 0.5"),
        ),
    )


class MemoryEvent(Base):
    """Append-only audit of every *proposed* memory delta, applied or not (ADR-0012). This is what
    makes a wrong profile explainable and a changed extractor replayable — without it, long-term
    memory is a black box."""

    __tablename__ = "memory_events"

    id: Mapped[uuid.UUID] = uuid_pk()
    student_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("students.id", ondelete="CASCADE"), nullable=False
    )
    session_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("sessions.id", ondelete="SET NULL")
    )
    message_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("messages.id", ondelete="SET NULL")
    )
    kind: Mapped[MemoryKind] = mapped_column(_pg_enum(MemoryKind, "memory_kind"), nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    confidence: Mapped[float | None] = mapped_column(Numeric(4, 3))
    applied: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=sa_false()
    )
    rejection_reason: Mapped[str | None] = mapped_column(Text)
    extractor_version: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = created_at_column()

    __table_args__ = (Index("ix_memory_events_student", "student_id", "created_at"),)


class StudyPlan(Base):
    __tablename__ = "study_plans"

    id: Mapped[uuid.UUID] = uuid_pk()
    student_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("students.id", ondelete="CASCADE"), nullable=False
    )
    title: Mapped[str] = mapped_column(Text, nullable=False)
    goal: Mapped[str | None] = mapped_column(Text)
    start_date: Mapped[date] = mapped_column(Date, nullable=False)
    end_date: Mapped[date] = mapped_column(Date, nullable=False)
    status: Mapped[PlanStatus] = mapped_column(
        _pg_enum(PlanStatus, "plan_status"),
        nullable=False,
        default=PlanStatus.ACTIVE,
        server_default="active",
    )
    created_at: Mapped[datetime] = created_at_column()

    items: Mapped[list["StudyPlanItem"]] = relationship(
        back_populates="plan", order_by="StudyPlanItem.day_index", cascade="all, delete-orphan"
    )

    __table_args__ = (CheckConstraint("end_date >= start_date", name="ck_study_plans_date_order"),)


class StudyPlanItem(Base):
    __tablename__ = "study_plan_items"

    id: Mapped[uuid.UUID] = uuid_pk()
    plan_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("study_plans.id", ondelete="CASCADE"), nullable=False
    )
    day_index: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    subject: Mapped[str] = mapped_column(Text, nullable=False)
    topic: Mapped[str] = mapped_column(Text, nullable=False)
    activity: Mapped[str] = mapped_column(Text, nullable=False)
    est_minutes: Mapped[int | None] = mapped_column(SmallInteger)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    plan: Mapped[StudyPlan] = relationship(back_populates="items")

    __table_args__ = (
        UniqueConstraint(
            "plan_id", "day_index", "subject", "topic", name="uq_study_plan_items_plan_day_topic"
        ),
    )


class Quiz(Base):
    __tablename__ = "quizzes"

    id: Mapped[uuid.UUID] = uuid_pk()
    student_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("students.id", ondelete="CASCADE"), nullable=False
    )
    session_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("sessions.id", ondelete="SET NULL")
    )
    subject: Mapped[str] = mapped_column(Text, nullable=False)
    topic: Mapped[str] = mapped_column(Text, nullable=False)
    difficulty: Mapped[str] = mapped_column(Text, nullable=False)
    language: Mapped[str] = mapped_column(Text, nullable=False, default="en", server_default="en")
    # [{id, prompt, expected, rubric, source_chunk_id}] — grounded in retrieved chunks wherever
    # possible; an ungrounded question (source_chunk_id is null) is flagged in eval, not hidden.
    questions: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, nullable=False)
    source_chunk_ids: Mapped[list[uuid.UUID]] = mapped_column(
        ARRAY(UUID(as_uuid=True)), nullable=False, server_default="{}"
    )
    created_at: Mapped[datetime] = created_at_column()

    __table_args__ = (
        CheckConstraint("difficulty IN ('easy','medium','hard')", name="ck_quizzes_difficulty"),
    )


class QuizAttempt(Base):
    __tablename__ = "quiz_attempts"

    id: Mapped[uuid.UUID] = uuid_pk()
    quiz_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("quizzes.id", ondelete="CASCADE"), nullable=False
    )
    student_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("students.id", ondelete="CASCADE"), nullable=False
    )
    answers: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    per_question: Mapped[list[dict[str, Any]]] = mapped_column(
        JSONB, nullable=False, server_default="[]"
    )
    score: Mapped[float | None] = mapped_column(Numeric(5, 2))
    max_score: Mapped[float | None] = mapped_column(Numeric(5, 2))
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    __table_args__ = (Index("ix_quiz_attempts_student", "student_id", "completed_at"),)
