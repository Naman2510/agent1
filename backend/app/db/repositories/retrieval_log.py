"""Retrieval audit trail: one row per `search_knowledge` call, distinct from the Phase 5 eval
suite's offline runs — this is what actually happened in a real conversation."""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import RetrievalLog


class RetrievalLogRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def record(
        self,
        *,
        query: str,
        retriever_config: dict[str, Any],
        candidate_ids: list[uuid.UUID],
        chosen_ids: list[uuid.UUID],
        session_id: uuid.UUID | None = None,
        message_id: uuid.UUID | None = None,
        query_language: str | None = None,
        scores: dict[str, Any] | None = None,
        latency_ms: int | None = None,
    ) -> RetrievalLog:
        row = RetrievalLog(
            session_id=session_id,
            message_id=message_id,
            query=query,
            query_language=query_language,
            retriever_config=retriever_config,
            candidate_ids=candidate_ids,
            chosen_ids=chosen_ids,
            scores=scores,
            latency_ms=latency_ms,
        )
        self._session.add(row)
        await self._session.flush()
        return row
