"""`finish_then_cancel`: database work completes before a cancellation proceeds (D8-04)."""

from __future__ import annotations

import asyncio

import pytest

from app.core.cancellation import finish_then_cancel


async def test_work_that_is_not_interrupted_returns_its_result() -> None:
    async def work() -> int:
        await asyncio.sleep(0)
        return 7

    assert await finish_then_cancel(work()) == 7


async def test_its_errors_reach_the_caller() -> None:
    async def work() -> None:
        raise ValueError("boom")

    with pytest.raises(ValueError, match="boom"):
        await finish_then_cancel(work())


async def test_a_cancelled_caller_waits_for_the_work_then_is_cancelled() -> None:
    """asyncio.shield alone would let the caller unwind while the work was still running — and
    the caller's cleanup then uses the same database session at the same time."""
    events: list[str] = []
    started = asyncio.Event()

    async def work() -> None:
        started.set()
        await asyncio.sleep(0.05)
        events.append("work finished")

    async def caller() -> None:
        try:
            await finish_then_cancel(work())
        finally:
            events.append("caller unwound")

    task = asyncio.create_task(caller())
    await started.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert events == ["work finished", "caller unwound"]


async def test_shield_alone_does_not_wait_which_is_why_this_exists() -> None:
    events: list[str] = []
    started = asyncio.Event()

    async def work() -> None:
        started.set()
        await asyncio.sleep(0.05)
        events.append("work finished")

    async def caller() -> None:
        try:
            await asyncio.shield(work())
        finally:
            events.append("caller unwound")

    task = asyncio.create_task(caller())
    await started.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert events == ["caller unwound"]
    await asyncio.sleep(0.1)
    assert events == ["caller unwound", "work finished"]
