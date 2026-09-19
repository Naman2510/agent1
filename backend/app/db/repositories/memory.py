"""Long-term memory persistence: student profile, per-topic mastery, and the audit trail.

Every mastery write goes through `StudentTopicRepository.apply_ewma` — there is no method that
replaces a mastery value outright, because ARCHITECTURE §12 forbids it: one utterance or one quiz
must not overwrite a student's record, only nudge it.
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import MemoryEvent, MemoryKind, StudentProfile, StudentTopic


class StudentProfileRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_or_create(self, student_id: uuid.UUID) -> StudentProfile:
        result = await self._session.execute(
            select(StudentProfile).where(StudentProfile.student_id == student_id)
        )
        profile = result.scalar_one_or_none()
        if profile is not None:
            return profile
        profile = StudentProfile(student_id=student_id)
        self._session.add(profile)
        await self._session.flush()
        return profile

    async def apply_update(
        self,
        student_id: uuid.UUID,
        *,
        digest: str | None = None,
        explanation_style: str | None = None,
        learning_preferences_patch: dict[str, Any] | None = None,
    ) -> StudentProfile:
        """Merge a proposed change into the profile, bumping `version` (DATA_MODEL §4).

        A patch, not a replacement: an unset field here leaves the existing value untouched, so
        one extractor run proposing only `explanation_style` cannot blank out the digest.
        """
        profile = await self.get_or_create(student_id)
        if digest is not None:
            profile.digest = digest
        if explanation_style is not None:
            profile.explanation_style = explanation_style
        if learning_preferences_patch:
            profile.learning_preferences = {
                **profile.learning_preferences,
                **learning_preferences_patch,
            }
        profile.version += 1
        profile.updated_at = datetime.now(UTC)
        await self._session.flush()
        return profile


class StudentTopicRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get(self, student_id: uuid.UUID, subject: str, topic: str) -> StudentTopic | None:
        result = await self._session.execute(
            select(StudentTopic).where(
                StudentTopic.student_id == student_id,
                StudentTopic.subject == subject,
                StudentTopic.topic == topic,
            )
        )
        return result.scalar_one_or_none()

    async def list_for_student(
        self, student_id: uuid.UUID, *, subject: str | None = None
    ) -> Sequence[StudentTopic]:
        stmt = select(StudentTopic).where(StudentTopic.student_id == student_id)
        if subject is not None:
            stmt = stmt.where(StudentTopic.subject == subject)
        stmt = stmt.order_by(StudentTopic.subject, StudentTopic.topic)
        result = await self._session.execute(stmt)
        return result.scalars().all()

    async def list_weak(self, student_id: uuid.UUID, *, limit: int = 5) -> Sequence[StudentTopic]:
        result = await self._session.execute(
            select(StudentTopic)
            .where(StudentTopic.student_id == student_id, StudentTopic.mastery < 0.5)
            .order_by(StudentTopic.mastery)
            .limit(limit)
        )
        return result.scalars().all()

    async def apply_ewma(
        self,
        student_id: uuid.UUID,
        subject: str,
        topic: str,
        *,
        sample: float,
        alpha: float,
    ) -> StudentTopic:
        """Blend one new observation into the running mastery estimate.

        `new = alpha * sample + (1 - alpha) * old`. `alpha` is the caller's to set — 0.3 for quiz
        evidence, 0.1 for a conversational signal (ARCHITECTURE §12) — because the two sources
        deserve different trust, not because this method has an opinion about it. Confidence
        grows with evidence, capped at 1.0, and never resets: it reflects how much has been
        observed, not how recent the last observation was.
        """
        if not 0.0 <= sample <= 1.0:
            raise ValueError(f"sample must be in [0, 1], got {sample}")
        if not 0.0 < alpha <= 1.0:
            raise ValueError(f"alpha must be in (0, 1], got {alpha}")

        row = await self.get(student_id, subject, topic)
        if row is None:
            row = StudentTopic(student_id=student_id, subject=subject, topic=topic)
            self._session.add(row)
            await self._session.flush()

        old_mastery = float(row.mastery)
        row.mastery = alpha * sample + (1 - alpha) * old_mastery
        row.confidence = min(1.0, float(row.confidence) + 0.1)
        row.evidence_count += 1
        row.last_seen_at = datetime.now(UTC)
        row.updated_at = datetime.now(UTC)
        await self._session.flush()
        return row


class MemoryEventRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def record(
        self,
        *,
        student_id: uuid.UUID,
        kind: MemoryKind,
        payload: dict[str, Any],
        extractor_version: str,
        session_id: uuid.UUID | None = None,
        message_id: uuid.UUID | None = None,
        confidence: float | None = None,
        applied: bool = False,
        rejection_reason: str | None = None,
    ) -> MemoryEvent:
        event = MemoryEvent(
            student_id=student_id,
            session_id=session_id,
            message_id=message_id,
            kind=kind,
            payload=payload,
            confidence=confidence,
            applied=applied,
            rejection_reason=rejection_reason,
            extractor_version=extractor_version,
        )
        self._session.add(event)
        await self._session.flush()
        return event

    async def list_for_student(
        self, student_id: uuid.UUID, *, limit: int = 50
    ) -> Sequence[MemoryEvent]:
        result = await self._session.execute(
            select(MemoryEvent)
            .where(MemoryEvent.student_id == student_id)
            .order_by(MemoryEvent.created_at.desc())
            .limit(limit)
        )
        return result.scalars().all()
