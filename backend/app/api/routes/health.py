"""Liveness and readiness.

Kept unauthenticated (an orchestrator cannot log in) but deliberately uninformative: readiness
reports up/down per dependency and never a driver error string, which would disclose hostnames
and versions.
"""

import redis.asyncio as redis
import structlog
from fastapi import APIRouter, Response, status
from sqlalchemy import text

from app.api.deps import DbDep, RedisDep, SettingsDep
from app.schemas.common import HealthResponse, ReadinessResponse

router = APIRouter(tags=["health"])
log = structlog.get_logger(__name__)


@router.get("/health", response_model=HealthResponse)
async def health(settings: SettingsDep) -> HealthResponse:
    return HealthResponse(status="ok", environment=settings.environment, version="0.1.0")


@router.get("/ready", response_model=ReadinessResponse)
async def ready(db: DbDep, client: RedisDep, response: Response) -> ReadinessResponse:
    db_state = "up"
    try:
        await db.execute(text("SELECT 1"))
    except Exception:
        log.error("readiness.database_down", exc_info=True)
        db_state = "down"

    redis_state = "up"
    try:
        await client.ping()
    except redis.RedisError:
        log.error("readiness.redis_down", exc_info=True)
        redis_state = "down"

    # Only the database makes an instance unready: it is the record of truth, and nothing works
    # without it. Redis holds nothing that cannot be rebuilt (ARCHITECTURE §13) and every use of it
    # degrades, so an instance without it still serves — and taking every instance out of rotation
    # for a Redis outage would turn a degraded service into none (docs/DEGRADATION.md).
    if db_state == "down":
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
        overall = "unavailable"
    else:
        overall = "ready" if redis_state == "up" else "degraded"
    return ReadinessResponse(status=overall, database=db_state, redis=redis_state)
