"""Conversation session and message persistence."""

import uuid
from collections.abc import Sequence
from datetime import UTC, datetime
from typing import Any, cast

from sqlalchemy import CursorResult, Numeric, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Message, MessageRole, Session, SessionStatus


class SessionRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create(
        self, *, student_id: uuid.UUID, transport: str, client_info: dict[str, Any]
    ) -> Session:
        row = Session(student_id=student_id, transport=transport, client_info=client_info)
        self._session.add(row)
        await self._session.flush()
        return row

    async def get_for_student(self, session_id: uuid.UUID, student_id: uuid.UUID) -> Session | None:
        """Scoped lookup. There is deliberately no unscoped get_by_id: an IDOR needs a caller to
        be able to ask for someone else's row, and this repository offers no way to."""
        result = await self._session.execute(
            select(Session).where(Session.id == session_id, Session.student_id == student_id)
        )
        return result.scalar_one_or_none()

    async def list_for_student(
        self, student_id: uuid.UUID, *, limit: int = 20, offset: int = 0
    ) -> Sequence[Session]:
        result = await self._session.execute(
            select(Session)
            .where(Session.student_id == student_id)
            .order_by(Session.started_at.desc())
            .limit(limit)
            .offset(offset)
        )
        return result.scalars().all()

    async def count_for_student(self, student_id: uuid.UUID) -> int:
        result = await self._session.execute(
            select(func.count()).select_from(Session).where(Session.student_id == student_id)
        )
        return int(result.scalar_one())

    async def end(
        self, session_id: uuid.UUID, student_id: uuid.UUID, status: SessionStatus
    ) -> bool:
        result = await self._session.execute(
            update(Session)
            .where(
                Session.id == session_id,
                Session.student_id == student_id,
                Session.status == SessionStatus.ACTIVE,
            )
            .values(status=status, ended_at=datetime.now(UTC))
        )
        return bool(cast(CursorResult[Any], result).rowcount)

    async def count_active(self) -> int:
        result = await self._session.execute(
            select(func.count()).select_from(Session).where(Session.status == SessionStatus.ACTIVE)
        )
        return int(result.scalar_one())

    async def count_total(self) -> int:
        result = await self._session.execute(select(func.count()).select_from(Session))
        return int(result.scalar_one())


class MessageRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def append(
        self,
        *,
        session_id: uuid.UUID,
        turn_index: int,
        seq: int,
        role: MessageRole,
        content: str,
        language: str | None = None,
        was_interrupted: bool = False,
        spoken_prefix_chars: int | None = None,
        unspoken_remainder: str | None = None,
        latency_ms: dict[str, Any] | None = None,
        token_usage: dict[str, Any] | None = None,
    ) -> Message:
        message = Message(
            session_id=session_id,
            turn_index=turn_index,
            seq=seq,
            role=role,
            content=content,
            language=language,
            was_interrupted=was_interrupted,
            spoken_prefix_chars=spoken_prefix_chars,
            unspoken_remainder=unspoken_remainder,
            latency_ms=latency_ms or {},
            token_usage=token_usage,
        )
        self._session.add(message)
        await self._session.flush()
        return message

    async def list_for_session(
        self, session_id: uuid.UUID, *, limit: int = 200
    ) -> Sequence[Message]:
        result = await self._session.execute(
            select(Message)
            .where(Message.session_id == session_id)
            .order_by(Message.turn_index, Message.seq)
            .limit(limit)
        )
        return result.scalars().all()

    async def next_turn_index(self, session_id: uuid.UUID) -> int:
        result = await self._session.execute(
            select(func.coalesce(func.max(Message.turn_index), -1)).where(
                Message.session_id == session_id
            )
        )
        return int(result.scalar_one()) + 1

    async def search_for_student(
        self,
        student_id: uuid.UUID,
        *,
        keyword: str | None = None,
        limit: int = 5,
    ) -> Sequence[Message]:
        """Past turns for `retrieve_previous_conversation` (ADR-0012: structured filters — here,
        "this student's own messages" — plus lexical search, not vector memory, for v1).

        Scoped through `Session.student_id` in the query itself, the same pattern
        `SessionRepository.get_for_student` uses: there is no version of this method that can
        search across students, so a prompt-injected id in a tool argument has nothing to reach
        for — this method does not even accept one.
        """
        stmt = (
            select(Message)
            .join(Session, Message.session_id == Session.id)
            .where(
                Session.student_id == student_id,
                Message.role.in_((MessageRole.USER, MessageRole.ASSISTANT)),
            )
        )
        if keyword:
            stmt = stmt.where(Message.content.ilike(f"%{keyword}%"))
        stmt = stmt.order_by(Message.created_at.desc()).limit(limit)
        result = await self._session.execute(stmt)
        return result.scalars().all()

    async def count_total(self) -> int:
        result = await self._session.execute(select(func.count()).select_from(Message))
        return int(result.scalar_one())

    async def average_llm_ttft_ms(self) -> tuple[float, int] | None:
        """Mean time-to-first-token across every assistant reply that recorded one, for the admin
        dashboard (EVALUATION.md's stage marks, persisted per-message since Phase 3).

        `->>'llm_ttft_ms'` is NULL for a message that never recorded the mark (an interrupted
        turn, a refusal with nothing to time); SQL aggregates skip NULLs on their own, so no
        explicit filter is needed to exclude them from either the average or the sample count.
        Returns `None` — never `0.0` — when there is nothing to average, so the caller can report
        "not_measured" rather than a misleading zero (the same rule `admin/health` already applies
        to `active_sessions`).
        """
        ttft = Message.latency_ms.op("->>")("llm_ttft_ms")
        result = await self._session.execute(
            select(func.avg(ttft.cast(Numeric)), func.count(ttft)).where(
                Message.role == MessageRole.ASSISTANT
            )
        )
        average, sample_size = result.one()
        if average is None or sample_size == 0:
            return None
        return float(average), int(sample_size)
