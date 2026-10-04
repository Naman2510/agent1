"""Backfill sessions.turn_count, which nothing maintained before Phase 7.

Every session read 0. The count is now kept with each student message (MessageRepository.append);
this sets existing sessions to what their transcripts say.

Revision ID: 0004
Revises: 0003
Create Date: 2026-09-26
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0004"
down_revision: str | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        UPDATE sessions SET turn_count = (
            SELECT count(*) FROM messages
            WHERE messages.session_id = sessions.id AND messages.role = 'user'
        )
        """
    )


def downgrade() -> None:
    # Nothing to undo: the counts are right under the earlier schema too.
    pass
