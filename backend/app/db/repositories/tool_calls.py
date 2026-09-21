"""Tool-call audit trail (ARCHITECTURE §8.3): one row per tool invocation, regardless of outcome."""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import ToolCall, ToolStatus


class ToolCallRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def record(
        self,
        *,
        session_id: uuid.UUID,
        turn_index: int,
        tool_name: str,
        arguments: dict[str, Any],
        status: ToolStatus,
        message_id: uuid.UUID | None = None,
        result: dict[str, Any] | None = None,
        error: str | None = None,
        duration_ms: int | None = None,
    ) -> ToolCall:
        row = ToolCall(
            session_id=session_id,
            message_id=message_id,
            turn_index=turn_index,
            tool_name=tool_name,
            arguments=arguments,
            result=result,
            status=status,
            error=error,
            duration_ms=duration_ms,
        )
        self._session.add(row)
        await self._session.flush()
        return row

    async def usage_summary(self) -> list[tuple[str, ToolStatus, int]]:
        """Every (tool, outcome) combination ever recorded, with its count — the admin dashboard's
        raw material. Deliberately not opinionated about what counts as a "failure": that
        interpretation (ARCHITECTURE §8.2's tool budgets, or which outcomes are reliability
        problems versus deliberate refusals) belongs to whoever reads this, not to the audit trail
        itself. Uses `ix_tool_calls_name_status`, the same index `tool_calls` was already given for
        this exact access pattern.
        """
        result = await self._session.execute(
            select(ToolCall.tool_name, ToolCall.status, func.count())
            .group_by(ToolCall.tool_name, ToolCall.status)
            .order_by(ToolCall.tool_name)
        )
        return [(name, status, int(count)) for name, status, count in result.all()]
