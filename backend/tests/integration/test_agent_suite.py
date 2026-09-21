"""The agent eval suite (EVALUATION.md §5.1) against a real database.

See eval/suites/agent.py's own docstring for what is and is not measured — in short, allowlist
coverage and pipeline mechanics are real; tool-selection accuracy against a real model's judgement
is not, for lack of an Anthropic API key in this sandbox.
"""

from __future__ import annotations

import pathlib
import uuid

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.agent.intent import Intent
from app.agent.tools.base import ToolContext
from app.agent.tools.registry import DEFAULT_REGISTRY
from app.db.models import Session, Student, User, UserRole
from app.providers.embedding.tfidf_svd import TfidfSvdEmbeddingProvider
from app.providers.reranker.base import NoopReranker
from app.rag.service import RagService
from eval.suites import agent as agent_suite

_REPO_ROOT = pathlib.Path(__file__).resolve().parents[3]
SCENARIOS_PATH = _REPO_ROOT / "datasets" / "v1" / "agent" / "scenarios.jsonl"


@pytest.fixture(autouse=True)
async def _clean_tables(engine):  # type: ignore[no-untyped-def]
    yield
    async with engine.begin() as conn:
        await conn.execute(
            text(
                "TRUNCATE tool_calls, quiz_attempts, quizzes, study_plan_items, study_plans, "
                "student_topics, student_profiles, sessions, students, users "
                "RESTART IDENTITY CASCADE"
            )
        )


async def _make_actor(db_session: AsyncSession, *, label: str) -> ToolContext:
    user = User(
        email=f"{label}-{uuid.uuid4().hex[:8]}@example.com",
        password_hash="x",
        role=UserRole.STUDENT,
    )
    db_session.add(user)
    await db_session.flush()
    student = Student(user_id=user.id, display_name=label)
    db_session.add(student)
    await db_session.flush()
    session = Session(student_id=student.id, transport="text")
    db_session.add(session)
    await db_session.flush()
    await db_session.commit()
    rag = RagService(db_session, embeddings=TfidfSvdEmbeddingProvider(), reranker=NoopReranker())
    return ToolContext(
        student_id=student.id,
        session_id=session.id,
        turn_index=0,
        db=db_session,
        rag=rag,
        citation_sources={},
    )


def test_the_dataset_has_scenarios_covering_every_tool_and_intent() -> None:
    scenarios = agent_suite.load_cases(SCENARIOS_PATH)
    assert len(scenarios) >= 14

    seen_intents = {s.intent_context for s in scenarios}
    assert seen_intents == {i.value for i in Intent}, "every intent should have at least one case"

    seen_tools = {t for s in scenarios for t in s.expected_tools}
    seen_tools |= {s.gated_vs_ungated_probe for s in scenarios if s.gated_vs_ungated_probe}
    assert seen_tools == DEFAULT_REGISTRY.all_names, "every registered tool should appear somewhere"


def test_allowlist_coverage_passes_for_every_scenario() -> None:
    """Pure, no DB: does INTENT_TOOLS actually support what each scenario expects and forbid what
    it shouldn't? This is the check that would have caught update_student_progress's dead-tool bug
    (PHASE_6_AUDIT.md) before it shipped."""
    scenarios = agent_suite.load_cases(SCENARIOS_PATH)
    for scenario in scenarios:
        check = agent_suite.check_allowlist_coverage(scenario)
        assert check.ok, (
            f"{scenario.id}: missing={check.missing_expected} "
            f"wrongly_allowed={check.wrongly_allowed_forbidden}"
        )


async def test_every_pipeline_scenario_completes_with_no_forbidden_tool_executed(
    db_session: AsyncSession,
) -> None:
    scenarios = [s for s in agent_suite.load_cases(SCENARIOS_PATH) if s.run_pipeline]
    assert scenarios, "at least one scenario must exercise the real pipeline"

    for scenario in scenarios:
        ctx = await _make_actor(db_session, label=scenario.id)
        outcome = await agent_suite.run_pipeline_scenario(
            scenario, registry=DEFAULT_REGISTRY, ctx=ctx
        )
        assert outcome.completed, f"{scenario.id} did not complete: {outcome}"
        assert not outcome.forbidden_tools_executed, f"{scenario.id}: {outcome}"
        if not scenario.expect_tool_error:
            assert set(scenario.expected_tools) <= outcome.executed_tools, scenario.id


async def test_an_unnecessary_but_allowed_call_is_flagged(db_session: AsyncSession) -> None:
    scenarios = {s.id: s for s in agent_suite.load_cases(SCENARIOS_PATH)}
    scenario = scenarios["agent-013"]
    assert scenario.unnecessary_tools == ["retrieve_previous_conversation"]

    ctx = await _make_actor(db_session, label="unnecessary-call")
    outcome = await agent_suite.run_pipeline_scenario(scenario, registry=DEFAULT_REGISTRY, ctx=ctx)

    assert outcome.unnecessary_tools_flagged == {"retrieve_previous_conversation"}


async def test_a_handler_raised_tool_error_is_surfaced_not_a_crash(
    db_session: AsyncSession,
) -> None:
    scenarios = {s.id: s for s in agent_suite.load_cases(SCENARIOS_PATH)}
    scenario = scenarios["agent-014"]
    assert scenario.expect_tool_error is True

    ctx = await _make_actor(db_session, label="tool-error")
    outcome = await agent_suite.run_pipeline_scenario(scenario, registry=DEFAULT_REGISTRY, ctx=ctx)

    assert outcome.tool_error_surfaced is True
    assert outcome.completed is True, "the loop must still finish after a handler error"


async def test_the_gate_earns_its_place_for_every_probed_scenario(db_session: AsyncSession) -> None:
    """For every scenario with a gated_vs_ungated_probe: the same attempted call must be blocked
    under the scenario's real gated allowlist and would succeed if every tool were offered instead
    — proof gating is not a no-op, holding the call itself fixed."""
    scenarios = [s for s in agent_suite.load_cases(SCENARIOS_PATH) if s.gated_vs_ungated_probe]
    assert len(scenarios) >= 3

    for scenario in scenarios:
        ctx = await _make_actor(db_session, label=scenario.id)
        probe = await agent_suite.run_gated_vs_ungated_probe(
            scenario, registry=DEFAULT_REGISTRY, ctx=ctx
        )
        assert probe.gate_earned_its_place, (
            f"{scenario.id}: gated_blocked={probe.gated_blocked_it} "
            f"ungated_executed={probe.ungated_executed_it}"
        )
