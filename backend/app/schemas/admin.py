"""The admin dashboard's data contract.

A metric reports its literal value `"not_measured"` rather than `0`/`0.0` wherever nothing backs
it yet — a zero would be indistinguishable from a real, measured zero (EVALUATION.md §8's rule,
already applied to `active_sessions` since Phase 1). This is why `latency` and `average_mastery`
are typed as a number *or* that literal: both are averages, undefined rather than zero when the
underlying sample is empty. Plain counts (`total_students`, `tool_failures`, ...) never take this
union — an empty table is a real, fully-known zero, not a missing measurement.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel

NotMeasured = Literal["not_measured"]


class LatencyStats(BaseModel):
    llm_ttft_ms_avg: float
    sample_size: int


class ToolUsageRow(BaseModel):
    tool_name: str
    ok: int = 0
    error: int = 0
    rejected: int = 0
    timeout: int = 0
    budget_exceeded: int = 0


class MasteryOverview(BaseModel):
    tracked_topics: int
    average_mastery: float | NotMeasured


class MemoryEventCounts(BaseModel):
    applied: int
    rejected: int
    total: int


class AdminDashboardResponse(BaseModel):
    active_sessions: int
    total_students: int
    total_sessions: int
    total_messages: int
    latency: LatencyStats | NotMeasured
    # Nothing in this system counts STT failures yet (ARCHITECTURE has no such log path) — this
    # is a plain string, not the NotMeasured union, because there is no "measured" case to union
    # against today.
    stt_failures: str
    tool_failures: int
    tool_rejections: int
    rag_failures: int
    tool_usage: list[ToolUsageRow]
    mastery: MasteryOverview
    memory_events: MemoryEventCounts
