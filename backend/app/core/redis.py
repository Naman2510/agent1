"""Redis client lifecycle. Uses are enumerated in ARCHITECTURE §13; nothing else is permitted."""

import redis.asyncio as redis

from app.core.config import Settings


def create_redis(settings: Settings) -> redis.Redis:
    return redis.Redis.from_url(
        str(settings.redis_url),
        encoding="utf-8",
        decode_responses=True,
        socket_connect_timeout=2,
        socket_timeout=2,
        health_check_interval=30,
    )
