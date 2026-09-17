"""Redis token-bucket rate limiting (SECURITY.md §4, ARCHITECTURE §13).

A token bucket rather than a fixed window: a fixed window lets a caller spend the whole minute's
allowance in the last second and the next minute's in the first, i.e. 2x the limit instantaneously.
The bucket is refilled continuously, so the average rate is the limit and short bursts are bounded
by the capacity.

Refill and spend happen in one Lua script so the read-modify-write is atomic across workers;
doing it in Python would race.
"""

import time
from dataclasses import dataclass
from enum import StrEnum

import redis.asyncio as redis
import structlog

from app.core.config import Settings

log = structlog.get_logger(__name__)

# KEYS[1]=bucket  ARGV: capacity, refill_per_sec, now, cost, ttl
_SCRIPT = """
local capacity = tonumber(ARGV[1])
local refill = tonumber(ARGV[2])
local now = tonumber(ARGV[3])
local cost = tonumber(ARGV[4])
local ttl = tonumber(ARGV[5])

local state = redis.call('HMGET', KEYS[1], 'tokens', 'ts')
local tokens = tonumber(state[1])
local ts = tonumber(state[2])
if tokens == nil or ts == nil then
    tokens = capacity
    ts = now
end

local elapsed = now - ts
if elapsed < 0 then elapsed = 0 end
tokens = math.min(capacity, tokens + elapsed * refill)

local allowed = 0
local retry_after = 0
if tokens >= cost then
    tokens = tokens - cost
    allowed = 1
else
    retry_after = math.ceil((cost - tokens) / refill)
    if retry_after < 1 then retry_after = 1 end
end

redis.call('HSET', KEYS[1], 'tokens', tokens, 'ts', now)
redis.call('EXPIRE', KEYS[1], ttl)
return {allowed, retry_after}
"""


class LimitClass(StrEnum):
    ANONYMOUS = "anon"
    AUTHENTICATED = "auth"
    AI = "ai"


@dataclass(frozen=True)
class Decision:
    allowed: bool
    retry_after: int


class RateLimiter:
    def __init__(self, client: redis.Redis, settings: Settings) -> None:
        self._client = client
        self._settings = settings
        self._script = client.register_script(_SCRIPT)

    def _capacity(self, limit_class: LimitClass) -> int:
        return {
            LimitClass.ANONYMOUS: self._settings.rate_limit_anonymous_per_min,
            LimitClass.AUTHENTICATED: self._settings.rate_limit_authenticated_per_min,
            LimitClass.AI: self._settings.rate_limit_ai_per_min,
        }[limit_class]

    async def check(self, limit_class: LimitClass, identity: str, *, cost: int = 1) -> Decision:
        if not self._settings.rate_limit_enabled:
            return Decision(allowed=True, retry_after=0)

        capacity = self._capacity(limit_class)
        refill_per_sec = capacity / 60.0
        key = f"rl:{limit_class}:{identity}"
        try:
            allowed, retry_after = await self._script(
                keys=[key],
                args=[capacity, refill_per_sec, time.time(), cost, 120],
            )
        except redis.RedisError:
            # Fail open on a limiter outage: a Redis blip should degrade protection, not take the
            # product down. Logged at warning so it cannot pass unnoticed.
            log.warning("rate_limit.unavailable", limit_class=str(limit_class), exc_info=True)
            return Decision(allowed=True, retry_after=0)

        return Decision(allowed=bool(allowed), retry_after=int(retry_after))
