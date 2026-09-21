"""Admin endpoints.

Phase 1 shipped only enough to prove the role gate works. Phase 7 makes `/admin/health` the admin
dashboard's real data source (its own original intent) rather than mostly placeholders — every
figure below is a real aggregate query against real tables, with `"not_measured"` reserved for the
one thing genuinely nothing tracks yet (`stt_failures`) rather than used as a catch-all default.
Evaluation and experiment endpoints still arrive in Phase 8 (they need `evaluation_runs`, which
does not exist yet).
"""

from fastapi import APIRouter, Depends

from app.api.deps import AdminDep, DbDep, rate_limit_authenticated
from app.db.models import ToolStatus
from app.db.repositories.memory import MemoryEventRepository, StudentTopicRepository
from app.db.repositories.sessions import MessageRepository, SessionRepository
from app.db.repositories.tool_calls import ToolCallRepository
from app.db.repositories.users import StudentRepository
from app.schemas.admin import (
    AdminDashboardResponse,
    LatencyStats,
    MasteryOverview,
    MemoryEventCounts,
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
