"""The admin dashboard's data contract.

A metric reports its literal value `"not_measured"` rather than `0`/`0.0` wherever nothing backs
it yet — a zero would be indistinguishable from a real, measured zero (EVALUATION.md §8's rule,
already applied to `active_sessions` since Phase 1). This is why `latency` and `average_mastery`
are typed as a number *or* that literal: both are averages, undefined rather than zero when the
underlying sample is empty. Plain counts (`total_students`, `tool_failures`, ...) never take this
union — an empty table is a real, fully-known zero, not a missing measurement.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Literal

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


# --- evaluation (EVALUATION.md §8) ---------------------------------------------------------


class HeadlineMetric(BaseModel):
    """One number worth showing for a run. `of` is the total a count is out of, if it has one."""

    key: str
    label: str
    unit: Literal["ratio", "ms", "count"]
    value: float
    of: float | None = None


class EvaluationRunSummary(BaseModel):
    id: uuid.UUID
    suite: str
    config_name: str
    dataset_version: str
    dataset_digest: str
    git_sha: str
    git_dirty: bool
    started_at: datetime
    finished_at: datetime | None
    case_count: int | None
    failed_count: int
    headlines: list[HeadlineMetric]
    reproduces_run_id: uuid.UUID | None


class GuardResult(BaseModel):
    metric: str
    mean_loss: float
    max_loss: float
    failed: bool


class ExperimentSummary(BaseModel):
    slug: str
    title: str
    hypothesis: str
    suite: str
    variable_changed: str
    decision: str
    rationale: str | None
    decided_at: datetime | None
    baseline_run_id: uuid.UUID | None
    candidate_run_id: uuid.UUID | None
    metric: str | None
    cases: int
    baseline_mean: float | None
    candidate_mean: float | None
    mean_gain: float | None
    gain_95ci: list[float] | None
    guards: list[GuardResult]


class EvaluationOverview(BaseModel):
    runs: list[EvaluationRunSummary]
    experiments: list[ExperimentSummary]


class FailingCase(BaseModel):
    case_id: str
    language: str | None
    input: dict[str, Any]
    expected: dict[str, Any] | None
    actual: dict[str, Any] | None
    notes: str | None


class RunFailures(BaseModel):
    run_id: uuid.UUID
    suite: str
    config_name: str
    failed_count: int
    cases: list[FailingCase]
