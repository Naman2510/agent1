"""Recorded evaluation runs against a real database: provenance, reproduction, isolation.

Gate 8 asks for every suite to be reproducible from a recorded config. These are the mechanics
that claim rests on: a run keeps what produced it, `--reproduce` runs it again from that record
alone, and it refuses — rather than passing — when the numbers or the data have moved.
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.db.models import Document, EvalStatus, EvaluationResult, EvaluationRun
from eval import runner
from eval.harness import SUITES
from eval.recording import CONFIGS, DATASETS, RunSpec, RunStore, SuiteOutcome, load_config


@pytest.fixture(autouse=True)
async def _clean_eval_tables(engine):  # type: ignore[no-untyped-def]
    yield
    async with engine.begin() as conn:
        await conn.execute(text("TRUNCATE experiments, evaluation_results, evaluation_runs"))


async def _record(
    settings: Settings, config: str = "lid.toml"
) -> tuple[RunSpec, SuiteOutcome, uuid.UUID]:
    spec = runner.build_spec(*load_config(CONFIGS / config), "v1")
    store = RunStore(settings)
    try:
        outcome, run_id = await runner.execute(spec, settings, record=True, store=store)
    finally:
        await store.close()
    assert run_id is not None
    return spec, outcome, run_id


async def test_a_recorded_run_keeps_its_provenance_and_every_case(
    settings: Settings, db_session: AsyncSession
) -> None:
    spec, outcome, run_id = await _record(settings)

    run = await db_session.get(EvaluationRun, run_id)
    assert run is not None
    assert run.status is EvalStatus.COMPLETED
    assert (run.suite, run.config_name, run.dataset_version) == ("lid", "lid", "v1")
    assert run.config == {"suite": "lid"}
    assert run.dataset_digest == spec.dataset_digest
    assert len(run.dataset_digest) == 64
    assert run.git_sha == spec.git_sha
    assert run.summary_metrics == outcome.summary
    assert run.finished_at is not None

    cases = select(func.count()).select_from(EvaluationResult)
    assert await db_session.scalar(cases.where(EvaluationResult.run_id == run_id)) == 88
    assert run.case_count == 88
    failed = await db_session.scalar(
        cases.where(EvaluationResult.run_id == run_id, EvaluationResult.passed.is_(False))
    )
    assert failed == sum(not case.passed for case in outcome.cases)


async def test_a_recorded_run_reproduces_and_the_reproduction_is_linked_to_it(
    settings: Settings, db_session: AsyncSession
) -> None:
    _, _, run_id = await _record(settings)

    assert await runner.reproduce(run_id, settings, record=True) == 0

    again = (
        await db_session.execute(
            select(EvaluationRun).where(EvaluationRun.reproduces_run_id == run_id)
        )
    ).scalar_one()
    assert again.status is EvalStatus.COMPLETED


async def test_a_run_whose_numbers_have_moved_does_not_reproduce(
    settings: Settings, db_session: AsyncSession
) -> None:
    _, _, run_id = await _record(settings)
    run = await db_session.get(EvaluationRun, run_id)
    assert run is not None
    signal = {**run.summary_metrics["signal"], "accuracy": 0.5}
    run.summary_metrics = {**run.summary_metrics, "signal": signal}
    await db_session.commit()

    assert await runner.reproduce(run_id, settings, record=False) == 1


async def test_a_run_over_data_that_has_since_changed_is_not_rerun_at_all(
    settings: Settings, db_session: AsyncSession
) -> None:
    _, _, run_id = await _record(settings)
    run = await db_session.get(EvaluationRun, run_id)
    assert run is not None
    run.dataset_digest = "0" * 64
    await db_session.commit()

    assert await runner.reproduce(run_id, settings, record=False) == 2


async def test_the_retrieval_suite_leaves_the_corpus_as_it_found_it_and_repeats_exactly(
    settings: Settings, db_session: AsyncSession
) -> None:
    """The suite ingests its own corpus inside a transaction it rolls back, so what the database
    held before survives untouched — and two runs agree to the last digit (D8-01)."""
    bystander = Document(
        title=f"Bystander {uuid.uuid4().hex[:8]}",
        subject="Testing",
        source_path="/bystander",
        source_hash=f"hash-{uuid.uuid4().hex}",
    )
    db_session.add(bystander)
    await db_session.commit()
    try:
        _, config = load_config(CONFIGS / "retrieval.toml")
        suite = SUITES["retrieval"]
        first = await suite.evaluate(config, DATASETS / "v1", False, settings)
        second = await suite.evaluate(config, DATASETS / "v1", False, settings)

        assert first.summary == second.summary
        assert first.summary["chunks"] == 19
        still_there = await db_session.scalar(
            select(func.count()).select_from(Document).where(Document.id == bystander.id)
        )
        assert still_there == 1
    finally:
        await db_session.delete(bystander)
        await db_session.commit()


async def test_the_agent_suites_leave_no_trace(
    settings: Settings, db_session: AsyncSession
) -> None:
    """They succeed by changing nothing, inside a transaction that is never committed. When the
    tool loop committed after each call itself, the first suite's actor was kept and the next
    could not create its own, and CI's tier T1 failed on exactly that. Committing is now the
    caller's decision (`run_agent_turn(after_tool_call=...)`), and these suites make none."""
    from app.db.models import User

    for name in ("agent", "injection"):  # CI's order
        _, config = load_config(CONFIGS / f"{name}.toml")
        await SUITES[name].evaluate(config, DATASETS / "v1", False, settings)
    kept = await db_session.scalar(
        select(func.count()).select_from(User).where(User.email == "eval-suite@example.invalid")
    )
    assert kept == 0
