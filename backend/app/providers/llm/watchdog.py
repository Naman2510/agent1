"""A model stream that has gone quiet, given up on.

The SDK's timeout bounds each HTTP read (`llm_timeout_seconds`, 30 s) and it retries twice, so an
upstream that accepted the request and then said nothing kept a voice student in silence for up to
a minute and a half before the apology. `StallGuard` bounds the silence itself: a stream that
produces no event for `stall_seconds` is abandoned as unavailable — which the conversation already
turns into a spoken apology — and the request is cancelled, not left running.

It wraps whichever provider is configured (app/providers/registry.py), so every caller of the model
is covered: the turn itself, the intent gate before it, and the memory work after it. The bound is
between events, not on the whole answer: a long answer that keeps arriving is never cut off.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator

from app.providers.base import ProviderInfo, ProviderUnavailableError
from app.providers.llm.base import LLMProvider, LLMRequest, StreamEvent


class StallGuard(LLMProvider):
    def __init__(self, inner: LLMProvider, *, stall_seconds: float) -> None:
        self._inner = inner
        self._stall_seconds = stall_seconds

    @property
    def info(self) -> ProviderInfo:
        return self._inner.info

    async def stream(self, request: LLMRequest) -> AsyncIterator[StreamEvent]:
        events = aiter(self._inner.stream(request))
        try:
            while True:
                try:
                    async with asyncio.timeout(self._stall_seconds):
                        event = await anext(events)
                except StopAsyncIteration:
                    return
                except TimeoutError as exc:
                    raise ProviderUnavailableError(
                        f"no response for {self._stall_seconds:g} s", provider=self.info.name
                    ) from exc
                yield event
        finally:
            await events.aclose()  # type: ignore[attr-defined]

    async def count_tokens(self, request: LLMRequest) -> int:
        return await self._inner.count_tokens(request)

    async def aclose(self) -> None:
        await self._inner.aclose()
