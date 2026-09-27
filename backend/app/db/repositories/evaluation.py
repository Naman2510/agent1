"""Reads of recorded evaluation runs and experiments, for the admin dashboard (EVALUATION.md §8).

The runs are written by the evaluation runner (backend/eval/recording.py); the server only reads
them, and never starts one.
"""

import uuid
from collections.abc import Sequence

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import EvalStatus, EvaluationResult, EvaluationRun, Experiment


class EvaluationRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def latest_runs(self) -> Sequence[EvaluationRun]:
        """The latest completed run of each config, by suite and config name.

        A window function rather than PostgreSQL's DISTINCT ON: SQLAlchemy 2.1 deprecates
        `distinct(*columns)`, and its replacement does not exist in 2.0.
        """
        ranked = (
            select(
                EvaluationRun.id,
                func.row_number()
                .over(
                    partition_by=(EvaluationRun.suite, EvaluationRun.config_name),
                    order_by=EvaluationRun.finished_at.desc(),
                )
                .label("recency"),
            )
            .where(EvaluationRun.status == EvalStatus.COMPLETED)
            .subquery()
        )
        result = await self._session.execute(
            select(EvaluationRun)
            .join(ranked, ranked.c.id == EvaluationRun.id)
            .where(ranked.c.recency == 1)
            .order_by(EvaluationRun.suite, EvaluationRun.config_name)
        )
        return result.scalars().all()

    async def failed_counts(self, run_ids: Sequence[uuid.UUID]) -> dict[uuid.UUID, int]:
        if not run_ids:
            return {}
        result = await self._session.execute(
            select(EvaluationResult.run_id, func.count())
            .where(EvaluationResult.run_id.in_(run_ids), EvaluationResult.passed.is_(False))
            .group_by(EvaluationResult.run_id)
        )
        return {run_id: int(count) for run_id, count in result.all()}

    async def get_run(self, run_id: uuid.UUID) -> EvaluationRun | None:
        return await self._session.get(EvaluationRun, run_id)

    async def failures(self, run_id: uuid.UUID, *, limit: int = 200) -> Sequence[EvaluationResult]:
        result = await self._session.execute(
            select(EvaluationResult)
            .where(EvaluationResult.run_id == run_id, EvaluationResult.passed.is_(False))
            .order_by(EvaluationResult.case_id)
            .limit(limit)
        )
        return result.scalars().all()

    async def experiments(self) -> Sequence[Experiment]:
        result = await self._session.execute(select(Experiment).order_by(Experiment.slug))
        return result.scalars().all()
