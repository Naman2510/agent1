"""`GET /v1/admin/health` as the admin dashboard's real data source (Phase 7).

Every figure is checked against rows this test seeds directly, not just "the endpoint responds" —
the point of this file is proving the aggregates are actually correct, and that a metric with no
data reports `"not_measured"` rather than a zero indistinguishable from a real one.
"""

from __future__ import annotations

import uuid

import pytest
from httpx import AsyncClient
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import (
    MemoryEvent,
    MemoryKind,
    Message,
    MessageRole,
    Session,
    Student,
    StudentTopic,
    ToolCall,
    ToolStatus,
    User,
    UserRole,
)


@pytest.fixture(autouse=True)
async def _clean_tables(engine):  # type: ignore[no-untyped-def]
    yield
    async with engine.begin() as conn:
        await conn.execute(
            text(
                "TRUNCATE tool_calls, memory_events, student_topics, messages, sessions, "
                "students, users RESTART IDENTITY CASCADE"
            )
        )


async def _make_admin(client: AsyncClient, db_session: AsyncSession, registered) -> dict:  # type: ignore[no-untyped-def]
    email, password, _ = await registered("boss")
    user = (await db_session.execute(select(User).where(User.email == email))).scalar_one()
    user.role = UserRole.ADMIN
    await db_session.commit()
    fresh = await client.post("/auth/login", json={"email": email, "password": password})
    return fresh.json()


async def _make_actor(db_session: AsyncSession, *, label: str) -> tuple[uuid.UUID, uuid.UUID]:
    user = User(email=f"{label}-{uuid.uuid4().hex[:8]}@example.com", password_hash="x")
    db_session.add(user)
    await db_session.flush()
    student = Student(user_id=user.id, display_name=label)
    db_session.add(student)
    await db_session.flush()
    session = Session(student_id=student.id, transport="text")
    db_session.add(session)
    await db_session.flush()
    return student.id, session.id


async def test_a_fresh_system_reports_real_zero_counts_and_honest_not_measured(
    client: AsyncClient, registered, auth_headers, db_session: AsyncSession
) -> None:  # type: ignore[no-untyped-def]
    admin_tokens = await _make_admin(client, db_session, registered)

    response = await client.get("/admin/health", headers=auth_headers(admin_tokens))
    assert response.status_code == 200
    body = response.json()

    # /auth/register always creates a Student row; there is no separate admin-registration path
    # (promote_to_admin only changes the user's role, seeding/test-only) — so the admin account
    # used to call this endpoint is itself one real student.
    assert body["total_students"] == 1
    assert body["total_sessions"] == 0
    assert body["total_messages"] == 0
    assert body["tool_failures"] == 0, "a real, known zero — not the same thing as not_measured"
    assert body["tool_rejections"] == 0
    assert body["rag_failures"] == 0
    assert body["tool_usage"] == []
    assert body["latency"] == "not_measured"
    assert body["mastery"] == {"tracked_topics": 0, "average_mastery": "not_measured"}
    assert body["memory_events"] == {"applied": 0, "rejected": 0, "total": 0}
    assert body["stt_failures"] == "not_measured"


async def test_tool_usage_is_broken_down_by_tool_and_outcome(
    client: AsyncClient, registered, auth_headers, db_session: AsyncSession
) -> None:  # type: ignore[no-untyped-def]
    _student_id, session_id = await _make_actor(db_session, label="tool-usage")
    db_session.add_all(
        [
            ToolCall(
                session_id=session_id,
                turn_index=0,
                tool_name="search_knowledge",
                arguments={},
                status=ToolStatus.OK,
            ),
            ToolCall(
                session_id=session_id,
                turn_index=1,
                tool_name="search_knowledge",
                arguments={},
                status=ToolStatus.ERROR,
                error="boom",
            ),
            ToolCall(
                session_id=session_id,
                turn_index=2,
                tool_name="update_student_progress",
                arguments={},
                status=ToolStatus.REJECTED,
                error="not in this turn's allowlist",
            ),
            ToolCall(
                session_id=session_id,
                turn_index=3,
                tool_name="update_student_progress",
                arguments={},
                status=ToolStatus.TIMEOUT,
            ),
        ]
    )
    await db_session.commit()
    admin_tokens = await _make_admin(client, db_session, registered)

    response = await client.get("/admin/health", headers=auth_headers(admin_tokens))
    body = response.json()

    usage = {row["tool_name"]: row for row in body["tool_usage"]}
    assert usage["search_knowledge"]["ok"] == 1
    assert usage["search_knowledge"]["error"] == 1
    assert usage["update_student_progress"]["rejected"] == 1
    assert usage["update_student_progress"]["timeout"] == 1

    # search_knowledge's 1 error + update_student_progress's 1 timeout = 2 real failures;
    # REJECTED is a working allowlist, not a failure, so it must not be counted as one.
    assert body["tool_failures"] == 2
    assert body["tool_rejections"] == 1
    assert body["rag_failures"] == 1, "only search_knowledge's own error counts as a RAG failure"


async def test_latency_reports_the_real_average_llm_time_to_first_token(
    client: AsyncClient, registered, auth_headers, db_session: AsyncSession
) -> None:  # type: ignore[no-untyped-def]
    _student_id, session_id = await _make_actor(db_session, label="latency")
    db_session.add_all(
        [
            Message(
                session_id=session_id,
                turn_index=0,
                seq=0,
                role=MessageRole.USER,
                content="hi",
            ),
            Message(
                session_id=session_id,
                turn_index=0,
                seq=1,
                role=MessageRole.ASSISTANT,
                content="hello",
                latency_ms={"llm_ttft_ms": 100, "turn_total_ms": 400},
            ),
            Message(
                session_id=session_id,
                turn_index=1,
                seq=1,
                role=MessageRole.ASSISTANT,
                content="again",
                latency_ms={"llm_ttft_ms": 300},
            ),
            # No llm_ttft_ms at all (e.g. an interrupted turn with nothing timed) — must not
            # count as a zero and drag the average down.
            Message(
                session_id=session_id,
                turn_index=2,
                seq=1,
                role=MessageRole.ASSISTANT,
                content="",
                latency_ms={},
            ),
        ]
    )
    await db_session.commit()
    admin_tokens = await _make_admin(client, db_session, registered)

    response = await client.get("/admin/health", headers=auth_headers(admin_tokens))
    body = response.json()

    assert body["total_messages"] == 4
    assert body["latency"] == {"llm_ttft_ms_avg": 200.0, "sample_size": 2}


async def test_mastery_overview_and_memory_event_counts_are_real(
    client: AsyncClient, registered, auth_headers, db_session: AsyncSession
) -> None:  # type: ignore[no-untyped-def]
    student_id, session_id = await _make_actor(db_session, label="mastery")
    db_session.add_all(
        [
            StudentTopic(student_id=student_id, subject="EMT", topic="KVL", mastery=0.8),
            StudentTopic(student_id=student_id, subject="EMT", topic="KCL", mastery=0.4),
            MemoryEvent(
                student_id=student_id,
                session_id=session_id,
                kind=MemoryKind.TOPIC_UPDATE,
                payload={},
                applied=True,
                extractor_version="memory-extractor-v1",
            ),
            MemoryEvent(
                student_id=student_id,
                session_id=session_id,
                kind=MemoryKind.OBSERVATION,
                payload={},
                applied=False,
                rejection_reason="confidence below threshold",
                extractor_version="memory-extractor-v1",
            ),
            MemoryEvent(
                student_id=student_id,
                session_id=session_id,
                kind=MemoryKind.OBSERVATION,
                payload={},
                applied=False,
                rejection_reason="confidence below threshold",
                extractor_version="memory-extractor-v1",
            ),
        ]
    )
    await db_session.commit()
    admin_tokens = await _make_admin(client, db_session, registered)

    response = await client.get("/admin/health", headers=auth_headers(admin_tokens))
    body = response.json()

    assert body["mastery"] == {"tracked_topics": 2, "average_mastery": 0.6}
    assert body["memory_events"] == {"applied": 1, "rejected": 2, "total": 3}


async def test_a_student_still_cannot_reach_the_admin_endpoint_after_these_changes(
    client: AsyncClient, registered, auth_headers
) -> None:  # type: ignore[no-untyped-def]
    _, _, tokens = await registered()
    response = await client.get("/admin/health", headers=auth_headers(tokens))
    assert response.status_code == 403
