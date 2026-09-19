"""Phase 5: RAG corpus — documents and document_chunks.

Arrives with the code that reads it (ADR-0015): Phase 1 created only identity and conversation
tables, and this is the first migration to need pgvector.

The embedding column is `vector(256)`, not the `vector(768)` in the original db/schema.sql design
reference. That file assumed `multilingual-e5-base`; this environment cannot reach Hugging Face to
fetch its weights, so the shipped embedder is TF-IDF + truncated SVD at 256 dimensions instead —
see the amendment to docs/adr/0006-embedding-model.md. The column will be widened (or a
side-column added, per DATA_MODEL.md §5) if a real multilingual embedder becomes reachable.

Revision ID: 0002
Revises: 0001
Create Date: 2026-09-19
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from pgvector.sqlalchemy import Vector
from sqlalchemy.dialects import postgresql

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

EMBEDDING_DIMENSIONS = 256

INGEST_STATUS = postgresql.ENUM(
    "pending", "parsing", "embedding", "ready", "failed", name="ingest_status", create_type=False
)


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")
    op.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")
    INGEST_STATUS.create(op.get_bind(), checkfirst=True)

    op.create_table(
        "documents",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("subject", sa.Text(), nullable=False),
        sa.Column("topic", sa.Text(), nullable=True),
        sa.Column("semester", sa.SmallInteger(), nullable=True),
        sa.Column("language", sa.String(length=16), server_default="en", nullable=False),
        sa.Column("source_path", sa.Text(), nullable=False),
        sa.Column("source_hash", sa.Text(), nullable=False),
        sa.Column("license", sa.Text(), nullable=True),
        sa.Column("page_count", sa.Integer(), nullable=True),
        sa.Column("ingest_status", INGEST_STATUS, server_default="pending", nullable=False),
        sa.Column(
            "metadata_", postgresql.JSONB(), server_default=sa.text("'{}'::jsonb"), nullable=False
        ),
        sa.Column("ingested_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_documents"),
        sa.UniqueConstraint("source_hash", name="uq_documents_source_hash"),
    )

    op.create_table(
        "document_chunks",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("document_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("chunk_index", sa.Integer(), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("heading_path", sa.Text(), nullable=True),
        sa.Column(
            "content_tsv",
            postgresql.TSVECTOR(),
            sa.Computed("to_tsvector('simple', content)", persisted=True),
            nullable=True,
        ),
        sa.Column("embedding", Vector(EMBEDDING_DIMENSIONS), nullable=True),
        sa.Column("embedding_model", sa.Text(), nullable=True),
        sa.Column("token_count", sa.Integer(), nullable=True),
        sa.Column("page_start", sa.Integer(), nullable=True),
        sa.Column("page_end", sa.Integer(), nullable=True),
        sa.Column("section", sa.Text(), nullable=True),
        sa.Column("difficulty", sa.Text(), nullable=True),
        sa.Column("language", sa.Text(), nullable=True),
        sa.Column(
            "metadata_", postgresql.JSONB(), server_default=sa.text("'{}'::jsonb"), nullable=False
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint(
            "difficulty IS NULL OR difficulty IN ('easy','medium','hard')",
            name="ck_document_chunks_difficulty",
        ),
        sa.ForeignKeyConstraint(
            ["document_id"],
            ["documents.id"],
            name="fk_document_chunks_document_id_documents",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_document_chunks"),
        sa.UniqueConstraint("document_id", "chunk_index", name="uq_document_chunks_doc_chunk"),
    )

    # HNSW over cosine distance, matching ADR-0005. `m`/`ef_construction` are pgvector defaults,
    # adequate at this corpus size; revisited only if the retrieval suite shows otherwise.
    op.execute(
        "CREATE INDEX ix_document_chunks_embedding ON document_chunks "
        "USING hnsw (embedding vector_cosine_ops) WITH (m = 16, ef_construction = 64)"
    )
    op.create_index(
        "ix_document_chunks_tsv", "document_chunks", ["content_tsv"], postgresql_using="gin"
    )
    op.execute(
        "CREATE INDEX ix_document_chunks_trgm ON document_chunks "
        "USING gin (content gin_trgm_ops)"
    )
    op.create_index(
        "ix_document_chunks_meta",
        "document_chunks",
        ["metadata_"],
        postgresql_using="gin",
        postgresql_ops={"metadata_": "jsonb_path_ops"},
    )
    op.create_index(
        "ix_document_chunks_filter", "document_chunks", ["language", "difficulty"]
    )


def downgrade() -> None:
    op.drop_table("document_chunks")
    op.drop_table("documents")
    INGEST_STATUS.drop(op.get_bind(), checkfirst=True)
    # vector and pg_trgm are left in place: another migration or extension may depend on them,
    # and dropping a shared extension in a downgrade is more dangerous than leaving it.
