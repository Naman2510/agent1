"""`app.core.background`: a fire-and-forget task must actually finish, and a failure inside one
must never vanish silently (a bare `asyncio.create_task` can do both)."""

from __future__ import annotations

import asyncio

import structlog.testing

from app.core.background import drain, spawn


async def test_a_spawned_task_runs_to_completion() -> None:
    ran = False

    async def _work() -> None:
        nonlocal ran
        await asyncio.sleep(0)
        ran = True

    spawn(_work(), name="test-task")
    await drain()
    assert ran is True


async def test_drain_waits_for_every_currently_tracked_task() -> None:
    order: list[int] = []

    async def _work(n: int, delay: float) -> None:
        await asyncio.sleep(delay)
        order.append(n)

    spawn(_work(1, 0.02), name="slow")
    spawn(_work(2, 0.0), name="fast")
    await drain()
    assert sorted(order) == [1, 2]


async def test_an_exception_is_logged_not_raised() -> None:
    async def _boom() -> None:
        raise ValueError("deliberate failure")

    with structlog.testing.capture_logs() as logs:
        spawn(_boom(), name="boomer")
        await drain()  # must not raise, and must not hang

    failures = [entry for entry in logs if entry["event"] == "background_task.failed"]
    assert len(failures) == 1
    assert failures[0]["task_name"] == "boomer"


async def test_drain_with_nothing_pending_returns_immediately() -> None:
    await drain()  # no prior spawn in this test — must not error


async def test_a_cancelled_task_is_not_reported_as_a_failure() -> None:
    async def _never_finishes() -> None:
        await asyncio.sleep(10)

    with structlog.testing.capture_logs() as logs:
        task = spawn(_never_finishes(), name="cancel-me")
        task.cancel()
        await drain()

    assert logs == []
