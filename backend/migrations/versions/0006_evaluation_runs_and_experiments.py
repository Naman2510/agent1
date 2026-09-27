"""Phase 8: evaluation runs, their per-case results, and experiments.

As designed in db/schema.sql, plus what reproducing a run needs: the dataset's content digest, the
config's name, whether the working tree was dirty, and a link from a reproduction to the run it
repeated. Experiments carry their decision rule, recorded before their runs.

Revision ID: 0006
Revises: 0005
Create Date: 2026-09-26
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0006"
down_revision: str | None = "0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "evaluation_runs",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("suite", sa.Text(), nullable=False),
        sa.Column("dataset_version", sa.Text(), nullable=False),
        sa.Column("dataset_digest", sa.Text(), nullable=False),
        sa.Column("config_name", sa.Text(), nullable=False),
        sa.Column("config", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("git_sha", sa.Text(), nullable=False),
        sa.Column("git_dirty", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("mlflow_run_id", sa.Text(), nullable=True),
        sa.Column(
            "status",
            sa.Enum("running", "completed", "failed", name="eval_status"),
            server_default="running",
            nullable=False,
        ),
        sa.Column(
            "summary_metrics",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default="{}",
            nullable=False,
        ),
        sa.Column("case_count", sa.Integer(), nullable=True),
        sa.Column("reproduces_run_id", sa.UUID(), nullable=True),
        sa.Column(
            "started_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(
            ["reproduces_run_id"],
            ["evaluation_runs.id"],
            name=op.f("fk_evaluation_runs_reproduces_run_id_evaluation_runs"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_evaluation_runs")),
    )
    op.create_index(
        "ix_evaluation_runs_suite_started", "evaluation_runs", ["suite", "started_at"], unique=False
    )
    op.create_table(
        "evaluation_results",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("run_id", sa.UUID(), nullable=False),
        sa.Column("case_id", sa.Text(), nullable=False),
        sa.Column("language", sa.Text(), nullable=True),
        sa.Column("input", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("expected", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("actual", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column(
            "metrics", postgresql.JSONB(astext_type=sa.Text()), server_default="{}", nullable=False
        ),
        sa.Column("passed", sa.Boolean(), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(
            ["run_id"],
            ["evaluation_runs.id"],
            name=op.f("fk_evaluation_results_run_id_evaluation_runs"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_evaluation_results")),
        sa.UniqueConstraint("run_id", "case_id", name=op.f("uq_evaluation_results_run_id_case_id")),
    )
    op.create_index(
        "ix_evaluation_results_failed",
        "evaluation_results",
        ["run_id"],
        unique=False,
        postgresql_where=sa.text("passed = false"),
    )
    op.create_table(
        "experiments",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("slug", sa.Text(), nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("hypothesis", sa.Text(), nullable=False),
        sa.Column("suite", sa.Text(), nullable=False),
        sa.Column("variable_changed", sa.Text(), nullable=False),
        sa.Column("decision_rule", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("baseline_run_id", sa.UUID(), nullable=True),
        sa.Column("candidate_run_id", sa.UUID(), nullable=True),
        sa.Column(
            "comparison",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default="{}",
            nullable=False,
        ),
        sa.Column(
            "decision",
            sa.Enum("adopt", "reject", "inconclusive", "pending", name="exp_decision"),
            server_default="pending",
            nullable=False,
        ),
        sa.Column("rationale", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["baseline_run_id"],
            ["evaluation_runs.id"],
            name=op.f("fk_experiments_baseline_run_id_evaluation_runs"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["candidate_run_id"],
            ["evaluation_runs.id"],
            name=op.f("fk_experiments_candidate_run_id_evaluation_runs"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_experiments")),
        sa.UniqueConstraint("slug", name=op.f("uq_experiments_slug")),
    )


def downgrade() -> None:
    op.drop_table("experiments")
    op.drop_index(
        "ix_evaluation_results_failed",
        table_name="evaluation_results",
        postgresql_where=sa.text("passed = false"),
    )
    op.drop_table("evaluation_results")
    op.drop_index("ix_evaluation_runs_suite_started", table_name="evaluation_runs")
    op.drop_table("evaluation_runs")
    sa.Enum(name="exp_decision").drop(op.get_bind(), checkfirst=True)
    sa.Enum(name="eval_status").drop(op.get_bind(), checkfirst=True)
