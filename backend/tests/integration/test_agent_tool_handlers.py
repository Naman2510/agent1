"""Tool handlers against a real database: EWMA arithmetic, row-scoping, and persistence.

Scoping is tested explicitly for every tool that reads or writes a specific row — a second
student's data must never be reachable, the same authority guarantee ARCHITECTURE §8.4 states for
the orchestrator as a whole, proven here at the handler level.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from pathlib import Path

import pytest
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.agent.tools.base import ToolContext, ToolExecutionError
from app.agent.tools.history import (
    RetrievePreviousConversationInput,
    retrieve_previous_conversation,
)
from app.agent.tools.knowledge import search_knowledge
from app.agent.tools.progress import (
    GetStudentProgressInput,
    UpdateStudentProgressInput,
    get_student_progress,
    update_student_progress,
)
from app.agent.tools.quiz import GenerateQuizInput, QuizQuestionInput, generate_quiz
from app.agent.tools.study import (
    CreateStudyPlanInput,
    GetStudyPlanInput,
    StudyPlanItemInput,
    create_study_plan,
    get_study_plan,
)
from app.db.models import MessageRole, RetrievalLog, Session, Student, User, UserRole
from app.db.repositories.sessions import MessageRepository
from app.providers.embedding.tfidf_svd import TfidfSvdEmbeddingProvider
from app.providers.reranker.base import NoopReranker
from app.rag.ingest import DocumentMetadata
from app.rag.service import RagService
from app.rag.tool_spec import SearchKnowledgeInput


@dataclass
class Actor:
    student_id: uuid.UUID
    session_id: uuid.UUID


@pytest.fixture(autouse=True)
async def _clean_tables(engine):  # type: ignore[no-untyped-def]
    yield
    async with engine.begin() as conn:
        await conn.execute(
            text(
                "TRUNCATE quiz_attempts, quizzes, study_plan_items, study_plans, "
                "memory_events, student_topics, student_profiles, retrieval_logs, "
                "document_chunks, documents RESTART IDENTITY CASCADE"
            )
        )


async def _make_actor(db_session: AsyncSession, *, label: str) -> Actor:
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
    return Actor(student_id=student.id, session_id=session.id)


@pytest.fixture
async def actor(db_session: AsyncSession) -> Actor:
    return await _make_actor(db_session, label="actor")


def _ctx(db_session: AsyncSession, actor: Actor, *, turn_index: int = 0) -> ToolContext:
    rag = RagService(db_session, embeddings=TfidfSvdEmbeddingProvider(), reranker=NoopReranker())
    return ToolContext(
        student_id=actor.student_id,
        session_id=actor.session_id,
        turn_index=turn_index,
        db=db_session,
        rag=rag,
        citation_sources={},
    )


# --- get_student_progress / update_student_progress --------------------------


async def test_update_student_progress_blends_toward_the_sample_not_onto_it(
    db_session: AsyncSession, actor: Actor
) -> None:
    ctx = _ctx(db_session, actor)
    # sample = 2/2 = 1.0; starting mastery is 0.5; alpha = 0.3 -> 0.3*1.0 + 0.7*0.5 = 0.65.
    result = await update_student_progress(
        UpdateStudentProgressInput(subject="EMT", topic="KVL", correct=2, total=2), ctx
    )
    assert result["mastery"] == pytest.approx(0.65)
    assert result["subject"] == "EMT"


async def test_a_second_update_moves_further_toward_repeated_evidence(
    db_session: AsyncSession, actor: Actor
) -> None:
    ctx = _ctx(db_session, actor)
    await update_student_progress(
        UpdateStudentProgressInput(subject="EMT", topic="KVL", correct=2, total=2), ctx
    )
    second = await update_student_progress(
        UpdateStudentProgressInput(subject="EMT", topic="KVL", correct=2, total=2), ctx
    )
    # 0.3*1.0 + 0.7*0.65 = 0.755 — closer to 1.0, never jumping straight to it in one update.
    assert second["mastery"] == pytest.approx(0.755)
    assert second["evidence_count"] == 2


async def test_one_bad_quiz_does_not_erase_a_good_history(
    db_session: AsyncSession, actor: Actor
) -> None:
    """ARCHITECTURE §12: EWMA, never a replacement — one data point must not overwrite the
    record."""
    ctx = _ctx(db_session, actor)
    for _ in range(5):
        await update_student_progress(
            UpdateStudentProgressInput(subject="EMT", topic="KVL", correct=2, total=2), ctx
        )
    after_good_streak = (await get_student_progress(GetStudentProgressInput(subject="EMT"), ctx))[
        "topics"
    ][0]["mastery"]
    assert after_good_streak > 0.9

    bad_result = await update_student_progress(
        UpdateStudentProgressInput(subject="EMT", topic="KVL", correct=0, total=2), ctx
    )
    assert 0.5 < bad_result["mastery"] < after_good_streak


async def test_get_student_progress_only_ever_sees_the_calling_student(
    db_session: AsyncSession, actor: Actor
) -> None:
    other = await _make_actor(db_session, label="other")
    await update_student_progress(
        UpdateStudentProgressInput(subject="EMT", topic="KVL", correct=2, total=2),
        _ctx(db_session, other),
    )

    result = await get_student_progress(GetStudentProgressInput(), _ctx(db_session, actor))
    assert result["topics"] == []


async def test_get_student_progress_filters_by_subject(
    db_session: AsyncSession, actor: Actor
) -> None:
    ctx = _ctx(db_session, actor)
    await update_student_progress(
        UpdateStudentProgressInput(subject="EMT", topic="KVL", correct=1, total=2), ctx
    )
    await update_student_progress(
        UpdateStudentProgressInput(subject="Circuit Theory", topic="Thevenin", correct=1, total=2),
        ctx,
    )
    result = await get_student_progress(GetStudentProgressInput(subject="EMT"), ctx)
    assert [t["subject"] for t in result["topics"]] == ["EMT"]


# --- retrieve_previous_conversation ------------------------------------------


async def test_retrieve_previous_conversation_finds_a_matching_past_turn(
    db_session: AsyncSession, actor: Actor
) -> None:
    messages = MessageRepository(db_session)
    await messages.append(
        session_id=actor.session_id,
        turn_index=0,
        seq=0,
        role=MessageRole.USER,
        content="Can you explain Thevenin's theorem?",
    )
    await messages.append(
        session_id=actor.session_id,
        turn_index=0,
        seq=1,
        role=MessageRole.ASSISTANT,
        content="Sure — Thevenin's theorem replaces a network with one source and one resistor.",
    )
    await db_session.commit()

    result = await retrieve_previous_conversation(
        RetrievePreviousConversationInput(keyword="Thevenin"), _ctx(db_session, actor)
    )
    assert result["found"] is True
    assert any("Thevenin" in turn["excerpt"] for turn in result["turns"])


async def test_retrieve_previous_conversation_never_finds_another_students_turns(
    db_session: AsyncSession, actor: Actor
) -> None:
    other = await _make_actor(db_session, label="other2")
    await MessageRepository(db_session).append(
        session_id=other.session_id,
        turn_index=0,
        seq=0,
        role=MessageRole.USER,
        content="This is another student's private question about waveguides.",
    )
    await db_session.commit()

    result = await retrieve_previous_conversation(
        RetrievePreviousConversationInput(keyword="waveguides"), _ctx(db_session, actor)
    )
    assert result["found"] is False


async def test_retrieve_previous_conversation_with_no_keyword_returns_recent_turns(
    db_session: AsyncSession, actor: Actor
) -> None:
    await MessageRepository(db_session).append(
        session_id=actor.session_id, turn_index=0, seq=0, role=MessageRole.USER, content="hello"
    )
    await db_session.commit()
    result = await retrieve_previous_conversation(
        RetrievePreviousConversationInput(), _ctx(db_session, actor)
    )
    assert result["found"] is True


# --- create_study_plan / get_study_plan --------------------------------------


async def test_create_then_get_study_plan_round_trips(
    db_session: AsyncSession, actor: Actor
) -> None:
    ctx = _ctx(db_session, actor)
    created = await create_study_plan(
        CreateStudyPlanInput(
            title="Revision week",
            start_date="2026-02-10",
            end_date="2026-02-12",
            items=[
                StudyPlanItemInput(
                    day_index=0, subject="EMT", topic="KVL", activity="Redo derivation"
                ),
                StudyPlanItemInput(
                    day_index=1, subject="EMT", topic="Maxwell", activity="Read notes"
                ),
            ],
        ),
        ctx,
    )
    assert created["item_count"] == 2

    fetched = await get_study_plan(GetStudyPlanInput(plan_id=created["plan_id"]), ctx)
    assert fetched["found"] is True
    assert fetched["title"] == "Revision week"
    assert len(fetched["items"]) == 2
    assert fetched["items"][0]["completed"] is False


async def test_get_study_plan_with_no_id_returns_the_active_plan(
    db_session: AsyncSession, actor: Actor
) -> None:
    ctx = _ctx(db_session, actor)
    await create_study_plan(
        CreateStudyPlanInput(
            title="Only plan",
            start_date="2026-02-10",
            end_date="2026-02-12",
            items=[StudyPlanItemInput(day_index=0, subject="EMT", topic="KVL", activity="revise")],
        ),
        ctx,
    )
    result = await get_study_plan(GetStudyPlanInput(), ctx)
    assert result["found"] is True
    assert result["title"] == "Only plan"


async def test_get_study_plan_cannot_reach_another_students_plan(
    db_session: AsyncSession, actor: Actor
) -> None:
    other = await _make_actor(db_session, label="other3")
    created = await create_study_plan(
        CreateStudyPlanInput(
            title="Other's plan",
            start_date="2026-02-10",
            end_date="2026-02-12",
            items=[StudyPlanItemInput(day_index=0, subject="EMT", topic="KVL", activity="revise")],
        ),
        _ctx(db_session, other),
    )

    result = await get_study_plan(
        GetStudyPlanInput(plan_id=created["plan_id"]), _ctx(db_session, actor)
    )
    assert result["found"] is False


async def test_get_study_plan_rejects_a_malformed_id_as_a_tool_error_not_a_crash(
    db_session: AsyncSession, actor: Actor
) -> None:
    with pytest.raises(ToolExecutionError):
        await get_study_plan(GetStudyPlanInput(plan_id="not-a-uuid"), _ctx(db_session, actor))


# --- generate_quiz -------------------------------------------------------------


async def test_generate_quiz_persists_questions_with_generated_ids(
    db_session: AsyncSession, actor: Actor
) -> None:
    ctx = _ctx(db_session, actor)
    result = await generate_quiz(
        GenerateQuizInput(
            subject="EMT",
            topic="KVL",
            difficulty="easy",
            questions=[
                QuizQuestionInput(
                    prompt="State KVL.", expected="Sum of voltages around a loop is zero."
                ),
                QuizQuestionInput(
                    prompt="State KCL.", expected="Sum of currents at a node is zero."
                ),
            ],
        ),
        ctx,
    )
    assert result["question_count"] == 2
    assert result["ungrounded_count"] == 2  # neither question cited a source chunk


async def test_generate_quiz_counts_grounded_questions_from_a_real_source_chunk(
    db_session: AsyncSession, actor: Actor, tmp_path: Path
) -> None:
    ctx = _ctx(db_session, actor)
    doc = tmp_path / "kvl.md"
    doc.write_text(
        "# Unit\n\n## 7.1 KVL\n\nKVL states voltages sum to zero.\n\n"
        "## 7.2 KCL\n\nKCL states currents sum to zero.\n",
        encoding="utf-8",
    )
    ingested = await ctx.rag.ingest_file(doc, DocumentMetadata(title="KVL", subject="EMT"))
    await db_session.commit()
    await ctx.rag.fit_and_embed_all()
    await db_session.commit()
    chunks = await search_knowledge(SearchKnowledgeInput(query="KVL"), ctx)
    assert chunks["found"] is True
    real_chunk_id = str(ctx.citation_sources["[1]"].id)

    result = await generate_quiz(
        GenerateQuizInput(
            subject="EMT",
            topic="KVL",
            difficulty="easy",
            questions=[
                QuizQuestionInput(
                    prompt="State KVL.", expected="Sum is zero.", source_chunk_id=real_chunk_id
                )
            ],
        ),
        ctx,
    )
    assert result["ungrounded_count"] == 0
    assert ingested.chunk_count == 2


# --- search_knowledge (real wiring, real retrieval_logs row) ------------------


async def test_search_knowledge_logs_a_retrieval_log_row(
    db_session: AsyncSession, actor: Actor, tmp_path: Path
) -> None:
    ctx = _ctx(db_session, actor)
    doc = tmp_path / "maxwell.md"
    doc.write_text(
        "# Unit\n\n## 12.1 Equations\n\nMaxwell's equations describe fields.\n\n"
        "## 12.2 Displacement\n\nDisplacement current fixes Ampere's law.\n",
        encoding="utf-8",
    )
    await ctx.rag.ingest_file(doc, DocumentMetadata(title="Maxwell", subject="EMT"))
    await db_session.commit()
    await ctx.rag.fit_and_embed_all()
    await db_session.commit()

    result = await search_knowledge(SearchKnowledgeInput(query="displacement current"), ctx)
    assert result["found"] is True

    logs = (await db_session.execute(select(RetrievalLog))).scalars().all()
    assert len(logs) == 1
    assert logs[0].session_id == actor.session_id
    assert logs[0].query == "displacement current"
    assert len(logs[0].chosen_ids) >= 1


async def test_two_search_knowledge_calls_in_one_turn_do_not_collide_on_ref_numbers(
    db_session: AsyncSession, actor: Actor, tmp_path: Path
) -> None:
    ctx = _ctx(db_session, actor)
    doc_a = tmp_path / "a.md"
    doc_a.write_text(
        "# U\n\n## 1.1 A\n\nFirst topic content here for testing purposes.\n\n"
        "## 1.2 B\n\nSecond section unrelated content.\n",
        encoding="utf-8",
    )
    await ctx.rag.ingest_file(doc_a, DocumentMetadata(title="Doc A", subject="EMT"))
    await db_session.commit()
    await ctx.rag.fit_and_embed_all()
    await db_session.commit()

    await search_knowledge(SearchKnowledgeInput(query="first topic"), ctx)
    first_call_refs = set(ctx.citation_sources.keys())
    await search_knowledge(SearchKnowledgeInput(query="second section"), ctx)
    all_refs = set(ctx.citation_sources.keys())

    assert first_call_refs, "first call must have found at least one source"
    assert all_refs - first_call_refs, "second call must add new, distinct ref numbers"
    assert len(all_refs) == len(ctx.citation_sources)  # no ref got overwritten by a collision
