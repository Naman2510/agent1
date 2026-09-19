"""Study plan and quiz persistence.

Every lookup that takes an entity id is scoped by `student_id` in the same query — there is no
`get_by_id` alone, so a plan or quiz id guessed or leaked cannot be read cross-student
(SessionRepository's `get_for_student` pattern, ARCHITECTURE §8.4).
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from datetime import UTC, date, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.db.models import PlanStatus, Quiz, QuizAttempt, StudyPlan, StudyPlanItem


class StudyPlanRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create_with_items(
        self,
        *,
        student_id: uuid.UUID,
        title: str,
        start_date: date,
        end_date: date,
        items: list[dict[str, Any]],
        goal: str | None = None,
    ) -> StudyPlan:
        plan = StudyPlan(
            student_id=student_id, title=title, goal=goal, start_date=start_date, end_date=end_date
        )
        self._session.add(plan)
        await self._session.flush()

        self._session.add_all(
            [
                StudyPlanItem(
                    plan_id=plan.id,
                    day_index=item["day_index"],
                    subject=item["subject"],
                    topic=item["topic"],
                    activity=item["activity"],
                    est_minutes=item.get("est_minutes"),
                )
                for item in items
            ]
        )
        await self._session.flush()
        return plan

    async def get_for_student(self, plan_id: uuid.UUID, student_id: uuid.UUID) -> StudyPlan | None:
        result = await self._session.execute(
            select(StudyPlan)
            .options(selectinload(StudyPlan.items))
            .where(StudyPlan.id == plan_id, StudyPlan.student_id == student_id)
        )
        return result.scalar_one_or_none()

    async def get_active_for_student(self, student_id: uuid.UUID) -> StudyPlan | None:
        """The plan a bare `get_study_plan()` call (no id) means: the most recently created plan
        still in progress."""
        result = await self._session.execute(
            select(StudyPlan)
            .options(selectinload(StudyPlan.items))
            .where(StudyPlan.student_id == student_id, StudyPlan.status == PlanStatus.ACTIVE)
            .order_by(StudyPlan.created_at.desc())
            .limit(1)
        )
        return result.scalar_one_or_none()


class QuizRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create(
        self,
        *,
        student_id: uuid.UUID,
        subject: str,
        topic: str,
        difficulty: str,
        questions: list[dict[str, Any]],
        session_id: uuid.UUID | None = None,
        language: str = "en",
        source_chunk_ids: list[uuid.UUID] | None = None,
    ) -> Quiz:
        quiz = Quiz(
            student_id=student_id,
            session_id=session_id,
            subject=subject,
            topic=topic,
            difficulty=difficulty,
            language=language,
            questions=questions,
            source_chunk_ids=source_chunk_ids or [],
        )
        self._session.add(quiz)
        await self._session.flush()
        return quiz

    async def get_for_student(self, quiz_id: uuid.UUID, student_id: uuid.UUID) -> Quiz | None:
        result = await self._session.execute(
            select(Quiz).where(Quiz.id == quiz_id, Quiz.student_id == student_id)
        )
        return result.scalar_one_or_none()

    async def record_attempt(
        self,
        *,
        quiz_id: uuid.UUID,
        student_id: uuid.UUID,
        answers: dict[str, Any],
        per_question: list[dict[str, Any]],
        score: float | None,
        max_score: float | None,
    ) -> QuizAttempt:
        attempt = QuizAttempt(
            quiz_id=quiz_id,
            student_id=student_id,
            answers=answers,
            per_question=per_question,
            score=score,
            max_score=max_score,
            completed_at=datetime.now(UTC),
        )
        self._session.add(attempt)
        await self._session.flush()
        return attempt

    async def list_attempts(
        self, quiz_id: uuid.UUID, student_id: uuid.UUID
    ) -> Sequence[QuizAttempt]:
        result = await self._session.execute(
            select(QuizAttempt).where(
                QuizAttempt.quiz_id == quiz_id, QuizAttempt.student_id == student_id
            )
        )
        return result.scalars().all()
