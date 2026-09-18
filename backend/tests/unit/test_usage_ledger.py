"""Spend cap and voice quota accounting (Gate 0 finding M-11)."""

from datetime import UTC, datetime

import fakeredis.aioredis
import pytest

from app.core.config import Settings
from app.providers.llm.base import TokenUsage
from app.services.usage import (
    SpendCapExceededError,
    UsageLedger,
    VoiceQuotaExceededError,
)

JAN = datetime(2026, 1, 15, 12, 0, tzinfo=UTC)
FEB = datetime(2026, 2, 1, 0, 30, tzinfo=UTC)


@pytest.fixture
def redis_client() -> fakeredis.aioredis.FakeRedis:
    return fakeredis.aioredis.FakeRedis(decode_responses=True)


def _ledger(redis_client, settings: Settings, cap: float | None) -> UsageLedger:  # type: ignore[no-untyped-def]
    return UsageLedger(redis_client, settings.model_copy(update={"monthly_spend_cap_usd": cap}))


async def test_no_cap_configured_never_refuses(redis_client, settings: Settings) -> None:  # type: ignore[no-untyped-def]
    """An unset cap must mean 'unlimited', not 'zero'."""
    ledger = _ledger(redis_client, settings, None)
    cost = ledger.price_turn("claude-opus-5", TokenUsage(input_tokens=10_000_000))
    await ledger.record_turn(cost, now=JAN)
    await ledger.check_spend_cap(now=JAN)  # must not raise


async def test_cap_refuses_once_reached(redis_client, settings: Settings) -> None:  # type: ignore[no-untyped-def]
    ledger = _ledger(redis_client, settings, cap=1.0)
    await ledger.check_spend_cap(now=JAN)  # fine at zero spend

    # $1.00 of input tokens at $5/MTok = 200k tokens.
    cost = ledger.price_turn("claude-opus-5", TokenUsage(input_tokens=200_000))
    assert cost.cost_usd == pytest.approx(1.0)
    await ledger.record_turn(cost, now=JAN)

    assert await ledger.monthly_spend_usd(now=JAN) == pytest.approx(1.0)
    with pytest.raises(SpendCapExceededError):
        await ledger.check_spend_cap(now=JAN)


async def test_spend_accumulates_without_float_drift(redis_client, settings: Settings) -> None:  # type: ignore[no-untyped-def]
    """Money is held as integer micro-dollars; 1000 small turns must not drift."""
    ledger = _ledger(redis_client, settings, cap=None)
    cost = ledger.price_turn("claude-opus-5", TokenUsage(input_tokens=200, output_tokens=20))
    for _ in range(1000):
        await ledger.record_turn(cost, now=JAN)
    expected = round(cost.cost_usd, 6) * 1000
    assert await ledger.monthly_spend_usd(now=JAN) == pytest.approx(expected, rel=1e-9)


async def test_the_counter_is_per_month(redis_client, settings: Settings) -> None:  # type: ignore[no-untyped-def]
    ledger = _ledger(redis_client, settings, cap=1.0)
    await ledger.record_turn(
        ledger.price_turn("claude-opus-5", TokenUsage(input_tokens=200_000)), now=JAN
    )
    with pytest.raises(SpendCapExceededError):
        await ledger.check_spend_cap(now=JAN)
    # A new month starts clean.
    await ledger.check_spend_cap(now=FEB)
    assert await ledger.monthly_spend_usd(now=FEB) == 0.0


async def test_zero_cost_turns_do_not_create_a_counter(redis_client, settings: Settings) -> None:  # type: ignore[no-untyped-def]
    ledger = _ledger(redis_client, settings, cap=None)
    await ledger.record_turn(
        ledger.price_turn("fake-llm-1", TokenUsage(input_tokens=99, output_tokens=99)), now=JAN
    )
    assert await ledger.monthly_spend_usd(now=JAN) == 0.0


async def test_voice_quota_is_per_student_per_day(redis_client, settings: Settings) -> None:  # type: ignore[no-untyped-def]
    tight = settings.model_copy(update={"rate_limit_voice_minutes_per_day": 1})
    ledger = UsageLedger(redis_client, tight)

    await ledger.check_voice_quota("student-a", now=JAN)
    total = await ledger.record_voice_seconds("student-a", 60, now=JAN)
    assert total == 60

    with pytest.raises(VoiceQuotaExceededError):
        await ledger.check_voice_quota("student-a", now=JAN)

    # One student exhausting their allowance must not affect another.
    await ledger.check_voice_quota("student-b", now=JAN)
    # Nor the same student tomorrow.
    await ledger.check_voice_quota("student-a", now=datetime(2026, 1, 16, 9, 0, tzinfo=UTC))


async def test_voice_seconds_accumulate_across_calls(redis_client, settings: Settings) -> None:  # type: ignore[no-untyped-def]
    """Metered as audio is consumed, so an abandoned session still counts what it used."""
    ledger = UsageLedger(redis_client, settings)
    for _ in range(5):
        await ledger.record_voice_seconds("student-a", 12, now=JAN)
    assert await ledger.voice_seconds_used("student-a", now=JAN) == 60


async def test_recording_non_positive_seconds_is_a_no_op(redis_client, settings: Settings) -> None:  # type: ignore[no-untyped-def]
    ledger = UsageLedger(redis_client, settings)
    assert await ledger.record_voice_seconds("student-a", 0, now=JAN) == 0
    assert await ledger.voice_seconds_used("student-a", now=JAN) == 0
