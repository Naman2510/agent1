"""Store each answer's citations; index a session's tool calls.

Citations were resolved per turn, sent once over the voice socket and then lost, so history could
not show where an answer came from, and a typed turn never showed it at all. They are now kept on
the assistant message as shown at the time.

Revision ID: 0005
Revises: 0004
Create Date: 2026-09-26
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0005"
down_revision: str | None = "0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "messages",
        sa.Column(
            "citations",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default="[]",
            nullable=False,
        ),
    )
    op.create_index(
        "ix_tool_calls_session_turn", "tool_calls", ["session_id", "turn_index"], unique=False
    )


def downgrade() -> None:
    op.drop_index("ix_tool_calls_session_turn", table_name="tool_calls")
    op.drop_column("messages", "citations")
