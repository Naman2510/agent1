"""Letting database work finish when a turn is cancelled (ARCHITECTURE §5.7).

A barge-in cancels the turn's task wherever it happens to be waiting. If that is a query, asyncpg
abandons the connection mid-protocol, SQLAlchemy invalidates it, and the session refuses every later
statement until it is rolled back. A voice connection holds one session for its whole life, so a
single well-timed interruption failed every turn after it (D8-04).

`asyncio.shield`, which the tool loop used, does not prevent that: the shielded call carries on in
the background while the cancelled turn unwinds — and writes its own record on the same session, at
the same time. `finish_then_cancel` waits instead: the work runs to completion, then the
cancellation proceeds. It is for database work only. Generation and synthesis must stop at once,
and do.
"""

from __future__ import annotations

import asyncio
import contextlib
from collections.abc import Awaitable
from typing import TypeVar

T = TypeVar("T")


async def finish_then_cancel(work: Awaitable[T]) -> T:
    """Await `work`; if the caller is cancelled meanwhile, let `work` finish, then re-raise.

    The work's own timeout (a tool's, say) bounds the wait. Its outcome is discarded when the
    caller was cancelled: the turn it belonged to is over.
    """
    task = asyncio.ensure_future(work)
    try:
        return await asyncio.shield(task)
    except asyncio.CancelledError:
        with contextlib.suppress(Exception):
            await task
        raise
