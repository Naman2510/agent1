"""Phase 6: agent tools, memory, study plans and quizzes.

Arrives with the code that reads it (ADR-0015): `retrieval_logs`, `student_profiles`,
`student_topics`, `memory_events`, `study_plans`, `study_plan_items`, `quizzes`, `quiz_attempts` —
every table `db/schema.sql` designed for this phase, exactly as designed (no embedding column here,
so none of the Phase 5 substitution concerns apply).

Revision ID: 0003
Revises: 0002
Create Date: 2026-09-19
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

PLAN_STATUS = postgresql.ENUM(
    "active", "completed", "abandoned", name="plan_status", create_type=False
)
MEMORY_KIND = postgresql.ENUM(
    "observation", "profile_update", "topic_update", name="memory_kind", create_type=False
)


def upgrade() -> None:
    PLAN_STATUS.create(op.get_bind(), checkfirst=True)
    MEMORY_KIND.create(op.get_bind(), checkfirst=True)

    op.create_table(
        "retrieval_logs",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("session_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("message_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("query", sa.Text(), nullable=False),
        sa.Column("query_language", sa.Text(), nullable=True),
        sa.Column("retriever_config", postgresql.JSONB(), nullable=False),
        sa.Column(
            "candidate_ids",
            postgresql.ARRAY(postgresql.UUID(as_uuid=True)),
            server_default="{}",
            nullable=False,
        ),
        sa.Column(
            "chosen_ids",
            postgresql.ARRAY(postgresql.UUID(as_uuid=True)),
            server_default="{}",
            nullable=False,
        ),
        sa.Column("scores", postgresql.JSONB(), nullable=True),
        sa.Column("latency_ms", sa.Integer(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(
            ["session_id"], ["sessions.id"], name="fk_retrieval_logs_session_id_sessions",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["message_id"], ["messages.id"], name="fk_retrieval_logs_message_id_messages",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_retrieval_logs"),
    )
    op.create_index(
        "ix_retrieval_logs_session", "retrieval_logs", ["session_id", "created_at"]
    )

    op.create_table(
        "student_profiles",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("student_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("digest", sa.Text(), server_default="", nullable=False),
        sa.Column(
            "learning_preferences",
            postgresql.JSONB(),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column("explanation_style", sa.Text(), nullable=True),
        sa.Column("version", sa.Integer(), server_default="1", nullable=False),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(
            ["student_id"], ["students.id"], name="fk_student_profiles_student_id_students",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_student_profiles"),
        sa.UniqueConstraint("student_id", name="uq_student_profiles_student_id"),
    )

    op.create_table(
        "student_topics",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("student_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("subject", sa.Text(), nullable=False),
        sa.Column("topic", sa.Text(), nullable=False),
        sa.Column("mastery", sa.Numeric(4, 3), server_default="0.500", nullable=False),
        sa.Column("confidence", sa.Numeric(4, 3), server_default="0.100", nullable=False),
        sa.Column("evidence_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column(
            "last_seen_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint("mastery BETWEEN 0 AND 1", name="ck_student_topics_mastery_range"),
        sa.CheckConstraint("confidence BETWEEN 0 AND 1", name="ck_student_topics_confidence_range"),
        sa.ForeignKeyConstraint(
            ["student_id"], ["students.id"], name="fk_student_topics_student_id_students",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_student_topics"),
        sa.UniqueConstraint(
            "student_id", "subject", "topic", name="uq_student_topics_student_subject_topic"
        ),
    )
    op.execute(
        "CREATE INDEX ix_student_topics_weak ON student_topics (student_id, mastery) "
        "WHERE mastery < 0.5"
    )

    op.create_table(
        "memory_events",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("student_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("session_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("message_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("kind", MEMORY_KIND, nullable=False),
        sa.Column("payload", postgresql.JSONB(), nullable=False),
        sa.Column("confidence", sa.Numeric(4, 3), nullable=True),
        sa.Column("applied", sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.Column("rejection_reason", sa.Text(), nullable=True),
        sa.Column("extractor_version", sa.Text(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(
            ["student_id"], ["students.id"], name="fk_memory_events_student_id_students",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["session_id"], ["sessions.id"], name="fk_memory_events_session_id_sessions",
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["message_id"], ["messages.id"], name="fk_memory_events_message_id_messages",
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_memory_events"),
    )
    op.create_index("ix_memory_events_student", "memory_events", ["student_id", "created_at"])

    op.create_table(
        "study_plans",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("student_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("goal", sa.Text(), nullable=True),
        sa.Column("start_date", sa.Date(), nullable=False),
        sa.Column("end_date", sa.Date(), nullable=False),
        sa.Column("status", PLAN_STATUS, server_default="active", nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint("end_date >= start_date", name="ck_study_plans_date_order"),
        sa.ForeignKeyConstraint(
            ["student_id"], ["students.id"], name="fk_study_plans_student_id_students",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_study_plans"),
    )

    op.create_table(
        "study_plan_items",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("plan_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("day_index", sa.SmallInteger(), nullable=False),
        sa.Column("subject", sa.Text(), nullable=False),
        sa.Column("topic", sa.Text(), nullable=False),
        sa.Column("activity", sa.Text(), nullable=False),
        sa.Column("est_minutes", sa.SmallInteger(), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["plan_id"], ["study_plans.id"], name="fk_study_plan_items_plan_id_study_plans",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_study_plan_items"),
        sa.UniqueConstraint(
            "plan_id", "day_index", "subject", "topic",
            name="uq_study_plan_items_plan_day_topic",
        ),
    )

    op.create_table(
        "quizzes",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("student_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("session_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("subject", sa.Text(), nullable=False),
        sa.Column("topic", sa.Text(), nullable=False),
        sa.Column("difficulty", sa.Text(), nullable=False),
        sa.Column("language", sa.Text(), server_default="en", nullable=False),
        sa.Column("questions", postgresql.JSONB(), nullable=False),
        sa.Column(
            "source_chunk_ids",
            postgresql.ARRAY(postgresql.UUID(as_uuid=True)),
            server_default="{}",
            nullable=False,
        ),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint("difficulty IN ('easy','medium','hard')", name="ck_quizzes_difficulty"),
        sa.ForeignKeyConstraint(
            ["student_id"], ["students.id"], name="fk_quizzes_student_id_students",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["session_id"], ["sessions.id"], name="fk_quizzes_session_id_sessions",
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_quizzes"),
    )

    op.create_table(
        "quiz_attempts",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("quiz_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("student_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("answers", postgresql.JSONB(), nullable=False),
        sa.Column("per_question", postgresql.JSONB(), server_default=sa.text("'[]'::jsonb"), nullable=False),
        sa.Column("score", sa.Numeric(5, 2), nullable=True),
        sa.Column("max_score", sa.Numeric(5, 2), nullable=True),
        sa.Column(
            "started_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["quiz_id"], ["quizzes.id"], name="fk_quiz_attempts_quiz_id_quizzes",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["student_id"], ["students.id"], name="fk_quiz_attempts_student_id_students",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_quiz_attempts"),
    )
    op.create_index("ix_quiz_attempts_student", "quiz_attempts", ["student_id", "completed_at"])


def downgrade() -> None:
    op.drop_table("quiz_attempts")
    op.drop_table("quizzes")
    op.drop_table("study_plan_items")
    op.drop_table("study_plans")
    op.drop_table("memory_events")
    op.drop_table("student_topics")
    op.drop_table("student_profiles")
    op.drop_table("retrieval_logs")
    MEMORY_KIND.drop(op.get_bind(), checkfirst=True)
    PLAN_STATUS.drop(op.get_bind(), checkfirst=True)
