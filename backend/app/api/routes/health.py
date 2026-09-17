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

    healthy = db_state == "up" and redis_state == "up"
    if not healthy:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    return ReadinessResponse(
        status="ready" if healthy else "degraded", database=db_state, redis=redis_state
    )
