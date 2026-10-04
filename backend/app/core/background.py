"""Fire-and-forget asyncio tasks that must outlive the request that started them.

Memory extraction and the short-term window fold (ARCHITECTURE §12) both run "off the critical
path" — after a turn's response has already been streamed to the student, not blocking it. A bare
`asyncio.create_task(...)` is not enough for that: nothing else holds a reference to the task, so
the event loop is free to garbage-collect it mid-execution (a documented asyncio footgun), and an
exception inside it would otherwise surface only as an unraisable "Task exception was never
retrieved" warning with no application-level log line.

`spawn` keeps the strong reference this needs and turns a swallowed exception into a structured log
event. `drain` exists for tests: the only honest way to assert "a memory delta is traceable end to
end" (Gate 6) is to wait for the background work to actually finish, not to race it.
"""

from __future__ import annotations

import asyncio
from collections.abc import Coroutine
from typing import Any

import structlog

log = structlog.get_logger(__name__)

_tasks: set[asyncio.Task[Any]] = set()


def spawn(coro: Coroutine[Any, Any, Any], *, name: str) -> asyncio.Task[Any]:
    """Schedule `coro` to run independently of whatever is running now, and track it."""
    task = asyncio.create_task(coro, name=name)
    _tasks.add(task)
    task.add_done_callback(_on_done)
    return task


def _on_done(task: asyncio.Task[Any]) -> None:
    _tasks.discard(task)
    if task.cancelled():
        return
    exc = task.exception()
    if exc is not None:
        log.error("background_task.failed", task_name=task.get_name(), exc_info=exc)


async def drain() -> None:
    """Wait for every currently-tracked task to finish. Test-only: production code has no reason
    to block on work that exists specifically to not be on the critical path."""
    pending = list(_tasks)
    if pending:
        await asyncio.gather(*pending, return_exceptions=True)
