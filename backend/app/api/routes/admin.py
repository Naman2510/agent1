"""Admin endpoints.

Phase 1 ships only what is needed to prove the role gate works and to make the dashboard's data
source real. Evaluation and experiment endpoints arrive in Phase 8.
"""

from fastapi import APIRouter, Depends

from app.api.deps import AdminDep, DbDep, rate_limit_authenticated
from app.db.repositories.sessions import SessionRepository

router = APIRouter(prefix="/admin", tags=["admin"])


@router.get("/health", dependencies=[Depends(rate_limit_authenticated)])
async def system_health(_: AdminDep, db: DbDep) -> dict[str, object]:
    """Real counts only. A metric with no data reports 'not_measured', never zero — a zero here
    would be indistinguishable from a healthy system (EVALUATION.md §8)."""
    return {
        "active_sessions": await SessionRepository(db).count_active(),
        "latency": "not_measured",
        "stt_failures": "not_measured",
        "tool_failures": "not_measured",
        "rag_failures": "not_measured",
    }
