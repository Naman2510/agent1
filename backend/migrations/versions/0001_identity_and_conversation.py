"""Phase 1: identity and conversation core.

Creates the tables Phase 1 actually uses. The RAG, memory, quiz, and evaluation tables are
designed in db/schema.sql and are created by the migrations of the phases that read them
(5, 6, 8), so that a migration always arrives with its code.

Revision ID: 0001
Revises: None
Create Date: 2026-09-17
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

USER_ROLE = postgresql.ENUM("student", "admin", name="user_role", create_type=False)
SESSION_STATUS = postgresql.ENUM(
    "active", "ended", "abandoned", "error", name="session_status", create_type=False
)
MESSAGE_ROLE = postgresql.ENUM(
    "user", "assistant", "system", "tool", name="message_role", create_type=False
)
TOOL_STATUS = postgresql.ENUM(
    "ok", "error", "rejected", "timeout", "budget_exceeded", name="tool_status", create_type=False
)


def upgrade() -> None:
    # citext gives case-insensitive email uniqueness in the database rather than relying on every
    # call site remembering to lowercase.
    op.execute("CREATE EXTENSION IF NOT EXISTS citext")

    USER_ROLE.create(op.get_bind(), checkfirst=True)
    SESSION_STATUS.create(op.get_bind(), checkfirst=True)
    MESSAGE_ROLE.create(op.get_bind(), checkfirst=True)
    TOOL_STATUS.create(op.get_bind(), checkfirst=True)

    op.create_table(
        "users",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("email", postgresql.CITEXT(), nullable=False),
        sa.Column("password_hash", sa.Text(), nullable=False),
        sa.Column("role", USER_ROLE, server_default="student", nullable=False),
        sa.Column("is_active", sa.Boolean(), server_default=sa.true(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.PrimaryKeyConstraint("id", name="pk_users"),
        sa.UniqueConstraint("email", name="uq_users_email"),
    )

    op.create_table(
        "refresh_tokens",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("token_hash", sa.Text(), nullable=False),
        sa.Column("family_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "issued_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("user_agent", sa.String(length=256), nullable=True),
        sa.CheckConstraint("expires_at > issued_at", name="ck_refresh_tokens_expiry_after_issue"),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name="fk_refresh_tokens_user_id_users", ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name="pk_refresh_tokens"),
        sa.UniqueConstraint("token_hash", name="uq_refresh_tokens_token_hash"),
    )
    op.create_index(
        "ix_refresh_tokens_user_active",
        "refresh_tokens",
        ["user_id"],
        postgresql_where=sa.text("revoked_at IS NULL"),
    )
    op.create_index("ix_refresh_tokens_family", "refresh_tokens", ["family_id"])

    op.create_table(
        "students",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("display_name", sa.String(length=120), nullable=False),
        sa.Column("institution", sa.String(length=200), nullable=True),
        sa.Column("semester", sa.SmallInteger(), nullable=True),
        sa.Column(
            "preferred_language", sa.String(length=16), server_default="auto", nullable=False
        ),
        sa.Column(
            "consent_audio_retention", sa.Boolean(), server_default=sa.false(), nullable=False
        ),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint(
            "semester IS NULL OR (semester BETWEEN 1 AND 12)", name="ck_students_semester_range"
        ),
        sa.CheckConstraint(
            "preferred_language IN ('en','hi','hi-Latn','ta','auto')",
            name="ck_students_language_allowed",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name="fk_students_user_id_users", ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name="pk_students"),
        sa.UniqueConstraint("user_id", name="uq_students_user_id"),
    )

    op.create_table(
        "sessions",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("student_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("status", SESSION_STATUS, server_default="active", nullable=False),
        sa.Column("transport", sa.String(length=32), server_default="websocket", nullable=False),
        sa.Column(
            "client_info", postgresql.JSONB(), server_default=sa.text("'{}'::jsonb"), nullable=False
        ),
        sa.Column(
            "started_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("ended_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("turn_count", sa.Integer(), server_default="0", nullable=False),
        sa.ForeignKeyConstraint(
            ["student_id"],
            ["students.id"],
            name="fk_sessions_student_id_students",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_sessions"),
    )
    op.create_index("ix_sessions_student_started", "sessions", ["student_id", "started_at"])

    op.create_table(
        "messages",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("session_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("turn_index", sa.Integer(), nullable=False),
        sa.Column("seq", sa.SmallInteger(), server_default="0", nullable=False),
        sa.Column("role", MESSAGE_ROLE, nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("unspoken_remainder", sa.Text(), nullable=True),
        sa.Column("language", sa.String(length=16), nullable=True),
        sa.Column("stt_confidence", sa.Numeric(precision=4, scale=3), nullable=True),
        sa.Column("was_interrupted", sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.Column("spoken_prefix_chars", sa.Integer(), nullable=True),
        sa.Column("audio_ref", sa.Text(), nullable=True),
        sa.Column("token_usage", postgresql.JSONB(), nullable=True),
        sa.Column(
            "latency_ms", postgresql.JSONB(), server_default=sa.text("'{}'::jsonb"), nullable=False
        ),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint(
            "spoken_prefix_chars IS NULL OR spoken_prefix_chars >= 0",
            name="ck_messages_spoken_prefix_non_negative",
        ),
        sa.CheckConstraint(
            "NOT was_interrupted OR role = 'assistant'",
            name="ck_messages_interrupted_only_assistant",
        ),
        sa.ForeignKeyConstraint(
            ["session_id"],
            ["sessions.id"],
            name="fk_messages_session_id_sessions",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_messages"),
        sa.UniqueConstraint("session_id", "turn_index", "seq", name="uq_messages_turn_seq"),
    )
    op.create_index("ix_messages_session_turn", "messages", ["session_id", "turn_index", "seq"])

    op.create_table(
        "tool_calls",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("session_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("message_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("turn_index", sa.Integer(), nullable=False),
        sa.Column("tool_name", sa.String(length=64), nullable=False),
        sa.Column("arguments", postgresql.JSONB(), nullable=False),
        sa.Column("result", postgresql.JSONB(), nullable=True),
        sa.Column("status", TOOL_STATUS, nullable=False),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("duration_ms", sa.Integer(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(
            ["message_id"],
            ["messages.id"],
            name="fk_tool_calls_message_id_messages",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["session_id"],
            ["sessions.id"],
            name="fk_tool_calls_session_id_sessions",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_tool_calls"),
    )
    op.create_index(
        "ix_tool_calls_name_status", "tool_calls", ["tool_name", "status", "created_at"]
    )

    op.create_table(
        "audit_log",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("actor_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("action", sa.String(length=64), nullable=False),
        sa.Column("target_type", sa.String(length=64), nullable=True),
        sa.Column("target_id", sa.String(length=64), nullable=True),
        sa.Column("ip_hash", sa.String(length=64), nullable=True),
        sa.Column(
            "detail", postgresql.JSONB(), server_default=sa.text("'{}'::jsonb"), nullable=False
        ),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(
            ["actor_id"], ["users.id"], name="fk_audit_log_actor_id_users", ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("id", name="pk_audit_log"),
    )
    op.create_index("ix_audit_log_actor", "audit_log", ["actor_id", "created_at"])


def downgrade() -> None:
    op.drop_table("audit_log")
    op.drop_table("tool_calls")
    op.drop_table("messages")
    op.drop_table("sessions")
    op.drop_table("students")
    op.drop_table("refresh_tokens")
    op.drop_table("users")
    TOOL_STATUS.drop(op.get_bind(), checkfirst=True)
    MESSAGE_ROLE.drop(op.get_bind(), checkfirst=True)
    SESSION_STATUS.drop(op.get_bind(), checkfirst=True)
    USER_ROLE.drop(op.get_bind(), checkfirst=True)
    # citext is left in place: another migration or extension may rely on it, and dropping a
    # shared extension in a downgrade is more dangerous than leaving it.
