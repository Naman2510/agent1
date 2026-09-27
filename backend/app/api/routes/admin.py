"""Admin endpoints.

Phase 1 shipped only enough to prove the role gate works. Phase 7 makes `/admin/health` the admin
dashboard's real data source (its own original intent) rather than mostly placeholders — every
figure below is a real aggregate query against real tables, with `"not_measured"` reserved for the
one thing genuinely nothing tracks yet (`stt_failures`) rather than used as a catch-all default.
Phase 8 adds the evaluation view (EVALUATION.md §8): each config's latest recorded run, the decided
experiments, and each run's failing cases. The server only reads what the evaluation runner
recorded; it never starts a run.
"""

import uuid
from typing import Any, Literal

from fastapi import APIRouter, Depends

from app.api.deps import AdminDep, DbDep, rate_limit_authenticated
from app.core.errors import NotFoundError
from app.db.models import EvaluationRun, Experiment, ToolStatus
from app.db.repositories.evaluation import EvaluationRepository
from app.db.repositories.memory import MemoryEventRepository, StudentTopicRepository
from app.db.repositories.sessions import MessageRepository, SessionRepository
from app.db.repositories.tool_calls import ToolCallRepository
from app.db.repositories.users import StudentRepository
from app.schemas.admin import (
    AdminDashboardResponse,
    EvaluationOverview,
    EvaluationRunSummary,
    ExperimentSummary,
    FailingCase,
    GuardResult,
    HeadlineMetric,
    LatencyStats,
    MasteryOverview,
    MemoryEventCounts,
    RunFailures,
    ToolUsageRow,
)

router = APIRouter(prefix="/admin", tags=["admin"])

# Outcomes that represent something going wrong, as distinct from a deliberate refusal
# (REJECTED — the allowlist or a schema did its job) or a deliberate cutoff (BUDGET_EXCEEDED —
# ARCHITECTURE §8.1's budgets working as designed).
_FAILURE_STATUSES = frozenset({ToolStatus.ERROR, ToolStatus.TIMEOUT})


@router.get(
    "/health",
    dependencies=[Depends(rate_limit_authenticated)],
    response_model=AdminDashboardResponse,
)
async def system_health(_: AdminDep, db: DbDep) -> AdminDashboardResponse:
    usage = await ToolCallRepository(db).usage_summary()
    by_tool: dict[str, ToolUsageRow] = {}
    tool_failures = 0
    tool_rejections = 0
    rag_failures = 0
    for tool_name, status, count in usage:
        row = by_tool.setdefault(tool_name, ToolUsageRow(tool_name=tool_name))
        setattr(row, status.value, getattr(row, status.value) + count)
        if status in _FAILURE_STATUSES:
            tool_failures += count
            if tool_name == "search_knowledge":
                rag_failures += count
        elif status is ToolStatus.REJECTED:
            tool_rejections += count

    ttft = await MessageRepository(db).average_llm_ttft_ms()
    tracked_topics, average_mastery = await StudentTopicRepository(db).mastery_overview()
    memory_counts = await MemoryEventRepository(db).counts_by_applied()

    return AdminDashboardResponse(
        active_sessions=await SessionRepository(db).count_active(),
        total_students=await StudentRepository(db).count(),
        total_sessions=await SessionRepository(db).count_total(),
        total_messages=await MessageRepository(db).count_total(),
        latency=(
            LatencyStats(llm_ttft_ms_avg=round(ttft[0], 1), sample_size=ttft[1])
            if ttft is not None
            else "not_measured"
        ),
        stt_failures="not_measured",
        tool_failures=tool_failures,
        tool_rejections=tool_rejections,
        rag_failures=rag_failures,
        tool_usage=sorted(by_tool.values(), key=lambda r: r.tool_name),
        mastery=MasteryOverview(
            tracked_topics=tracked_topics,
            average_mastery=(
                round(average_mastery, 3) if average_mastery is not None else "not_measured"
            ),
        ),
        memory_events=MemoryEventCounts(
            applied=memory_counts.get(True, 0),
            rejected=memory_counts.get(False, 0),
            total=sum(memory_counts.values()),
        ),
    )


# --- evaluation ------------------------------------------------------------------------------

Unit = Literal["ratio", "ms", "count"]

# The few numbers worth a glance for each suite: (summary key, label, unit, key of the total it
# is out of). Everything else is in the run's record, and in MLflow.
HEADLINES: dict[str, tuple[tuple[str, str, Unit, str | None], ...]] = {
    "lid": (
        ("signal.accuracy", "accuracy", "ratio", None),
        ("signal.macro_f1", "macro F1", "ratio", None),
        ("routed.accuracy", "routed accuracy", "ratio", None),
    ),
    "retrieval": (
        ("ndcg@10", "nDCG@10", "ratio", None),
        ("mrr", "MRR", "ratio", None),
        ("recall@5", "recall@5", "ratio", None),
    ),
    "voice": (
        ("endpoint_ms_mean", "turn end", "ms", None),
        ("cut_off_rate", "cut off", "ratio", None),
        ("false_turns", "false turns", "count", None),
    ),
    "agent": (
        ("allowlist_coverage_ok", "allowlist cases", "count", "allowlist_coverage_total"),
        ("pipeline_forbidden_tool_leaked", "forbidden tools reached", "count", None),
    ),
    "injection": (
        ("blocked", "attacks blocked", "count", "total_attempted_calls"),
        ("executed", "attacks executed", "count", None),
    ),
}


def _lookup(summary: dict[str, Any], dotted: str) -> float | None:
    value: Any = summary
    for part in dotted.split("."):
        if not isinstance(value, dict) or part not in value:
            return None
        value = value[part]
    if isinstance(value, bool) or not isinstance(value, int | float):
        return None
    return float(value)


def headlines(suite: str, summary: dict[str, Any]) -> list[HeadlineMetric]:
    """A suite's headline metrics, as far as its summary has them."""
    metrics = []
    for key, label, unit, of in HEADLINES.get(suite, ()):
        value = _lookup(summary, key)
        if value is not None:
            total = _lookup(summary, of) if of else None
            metrics.append(HeadlineMetric(key=key, label=label, unit=unit, value=value, of=total))
    return metrics


def _run_summary(run: EvaluationRun, failed: int) -> EvaluationRunSummary:
    return EvaluationRunSummary(
        id=run.id,
        suite=run.suite,
        config_name=run.config_name,
        dataset_version=run.dataset_version,
        dataset_digest=run.dataset_digest,
        git_sha=run.git_sha,
        git_dirty=run.git_dirty,
        started_at=run.started_at,
        finished_at=run.finished_at,
        case_count=run.case_count,
        failed_count=failed,
        headlines=headlines(run.suite, run.summary_metrics or {}),
        reproduces_run_id=run.reproduces_run_id,
    )


def _experiment_summary(experiment: Experiment) -> ExperimentSummary:
    c = experiment.comparison or {}
    interval = c.get("gain_95ci")
    return ExperimentSummary(
        slug=experiment.slug,
        title=experiment.title,
        hypothesis=experiment.hypothesis,
        suite=experiment.suite,
        variable_changed=experiment.variable_changed,
        decision=str(experiment.decision),
        rationale=experiment.rationale,
        decided_at=experiment.decided_at,
        baseline_run_id=experiment.baseline_run_id,
        candidate_run_id=experiment.candidate_run_id,
        metric=c.get("metric"),
        cases=int(c.get("cases", 0)),
        baseline_mean=c.get("baseline_mean"),
        candidate_mean=c.get("candidate_mean"),
        mean_gain=c.get("mean_gain"),
        gain_95ci=[float(v) for v in interval] if interval else None,
        guards=[
            GuardResult(
                metric=metric,
                mean_loss=float(guard["mean_loss"]),
                max_loss=float(guard["max_loss"]),
                failed=bool(guard["failed"]),
            )
            for metric, guard in (c.get("guards") or {}).items()
        ],
    )


@router.get(
    "/evaluation",
    dependencies=[Depends(rate_limit_authenticated)],
    response_model=EvaluationOverview,
)
async def evaluation_overview(_: AdminDep, db: DbDep) -> EvaluationOverview:
    """Each config's latest recorded run, and every decided experiment. Empty lists, not zeros,
    when nothing has been recorded in this database."""
    repo = EvaluationRepository(db)
    runs = await repo.latest_runs()
    failed = await repo.failed_counts([run.id for run in runs])
    return EvaluationOverview(
        runs=[_run_summary(run, failed.get(run.id, 0)) for run in runs],
        experiments=[_experiment_summary(e) for e in await repo.experiments()],
    )


@router.get(
    "/evaluation/runs/{run_id}/failures",
    dependencies=[Depends(rate_limit_authenticated)],
    response_model=RunFailures,
)
async def run_failures(run_id: uuid.UUID, _: AdminDep, db: DbDep) -> RunFailures:
    """The failure-case browser: a run's failing cases, as recorded."""
    repo = EvaluationRepository(db)
    run = await repo.get_run(run_id)
    if run is None:
        raise NotFoundError("Evaluation run not found.")
    cases = await repo.failures(run_id)
    failed = (await repo.failed_counts([run_id])).get(run_id, 0)
    return RunFailures(
        run_id=run.id,
        suite=run.suite,
        config_name=run.config_name,
        failed_count=failed,
        cases=[
            FailingCase(
                case_id=r.case_id,
                language=r.language,
                input=r.input,
                expected=r.expected,
                actual=r.actual,
                notes=r.notes,
            )
            for r in cases
        ],
    )
