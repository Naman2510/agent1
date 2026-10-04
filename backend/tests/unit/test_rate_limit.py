"""Token-bucket rate limiter behaviour."""

import time
from unittest.mock import patch

import fakeredis.aioredis
import pytest
import redis.asyncio as redis_async

from app.core.config import Settings
from app.core.rate_limit import Decision, LimitClass, RateLimiter


@pytest.fixture
def limiter(settings: Settings, redis_client: fakeredis.aioredis.FakeRedis) -> RateLimiter:
    return RateLimiter(redis_client, settings)


async def test_allows_up_to_capacity_then_refuses(limiter: RateLimiter, settings: Settings) -> None:
    capacity = settings.rate_limit_anonymous_per_min
    for i in range(capacity):
        decision = await limiter.check(LimitClass.ANONYMOUS, "ip-1")
        assert decision.allowed, f"request {i + 1} of {capacity} should be allowed"

    refused = await limiter.check(LimitClass.ANONYMOUS, "ip-1")
    assert refused.allowed is False
    assert refused.retry_after >= 1, "a 429 must tell the caller when to come back"


async def test_buckets_are_isolated_per_identity(limiter: RateLimiter, settings: Settings) -> None:
    for _ in range(settings.rate_limit_anonymous_per_min):
        await limiter.check(LimitClass.ANONYMOUS, "noisy-ip")
    assert (await limiter.check(LimitClass.ANONYMOUS, "noisy-ip")).allowed is False
    # One caller exhausting their bucket must not affect anybody else.
    assert (await limiter.check(LimitClass.ANONYMOUS, "quiet-ip")).allowed is True


async def test_buckets_are_isolated_per_class(limiter: RateLimiter, settings: Settings) -> None:
    for _ in range(settings.rate_limit_ai_per_min):
        await limiter.check(LimitClass.AI, "user-1")
    assert (await limiter.check(LimitClass.AI, "user-1")).allowed is False
    # Exhausting the expensive class must not lock the user out of reading their history.
    assert (await limiter.check(LimitClass.AUTHENTICATED, "user-1")).allowed is True


async def test_bucket_refills_over_time(limiter: RateLimiter, settings: Settings) -> None:
    capacity = settings.rate_limit_anonymous_per_min
    start = time.time()
    with patch("app.core.rate_limit.time.time", return_value=start):
        for _ in range(capacity):
            await limiter.check(LimitClass.ANONYMOUS, "ip-refill")
        assert (await limiter.check(LimitClass.ANONYMOUS, "ip-refill")).allowed is False

    # Half a minute later, half the capacity is back — this is what distinguishes a token
    # bucket from a fixed window.
    with patch("app.core.rate_limit.time.time", return_value=start + 30):
        allowed = 0
        for _ in range(capacity):
            if (await limiter.check(LimitClass.ANONYMOUS, "ip-refill")).allowed:
                allowed += 1
        assert allowed == pytest.approx(capacity // 2, abs=1)


async def test_never_exceeds_capacity_after_a_long_idle_period(
    limiter: RateLimiter, settings: Settings
) -> None:
    """Refill must be clamped: an hour idle does not grant an hour's worth of tokens."""
    capacity = settings.rate_limit_anonymous_per_min
    start = time.time()
    with patch("app.core.rate_limit.time.time", return_value=start):
        await limiter.check(LimitClass.ANONYMOUS, "ip-idle")
    with patch("app.core.rate_limit.time.time", return_value=start + 3600):
        allowed = 0
        for _ in range(capacity * 3):
            if (await limiter.check(LimitClass.ANONYMOUS, "ip-idle")).allowed:
                allowed += 1
        assert allowed == capacity


async def test_disabled_limiter_allows_everything(
    settings: Settings, redis_client: fakeredis.aioredis.FakeRedis
) -> None:
    permissive = settings.model_copy(update={"rate_limit_enabled": False})
    limiter = RateLimiter(redis_client, permissive)
    for _ in range(settings.rate_limit_anonymous_per_min * 2):
        assert (await limiter.check(LimitClass.ANONYMOUS, "ip-x")).allowed


async def test_fails_open_when_redis_is_unavailable(settings: Settings) -> None:
    """A limiter outage should weaken protection, not take the product down."""

    class BrokenRedis:
        def register_script(self, _script: str):  # type: ignore[no-untyped-def]
            async def _raise(*_args, **_kwargs):  # type: ignore[no-untyped-def]
                raise redis_async.ConnectionError("redis is down")

            return _raise

    limiter = RateLimiter(BrokenRedis(), settings)  # type: ignore[arg-type]
    assert await limiter.check(LimitClass.ANONYMOUS, "ip-1") == Decision(
        allowed=True, retry_after=0
    )
