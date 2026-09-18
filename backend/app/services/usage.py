"""Cost and quota accounting (Gate 0 finding M-11).

Three jobs:

1. **Record** what each turn cost, so "cost per conversation" is a measured number rather than an
   arithmetic guess.
2. **Refuse** work once a configured monthly ceiling is reached.
3. **Meter** voice minutes per student per day, which is the control that actually bounds spend on
   an interactive voice product.

Counters live in Redis because they are incremented many times per minute and are cheap to
rebuild from `messages.token_usage` if lost (ARCHITECTURE §13). Money is counted in integer
micro-dollars: accumulating floats in a shared counter drifts, and drift in a spend cap is the
kind of bug that is discovered on an invoice.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

import redis.asyncio as redis
import structlog

from app.core.config import Settings
from app.core.errors import AppError
from app.core.pricing import estimate_cost_usd
from app.providers.llm.base import TokenUsage

log = structlog.get_logger(__name__)

_MICRO = 1_000_000
# Counters outlive their period so a month's spend is still inspectable after it ends.
_MONTH_TTL_SECONDS = 70 * 24 * 3600
_DAY_TTL_SECONDS = 3 * 24 * 3600


class SpendCapExceededError(AppError):
    status_code = 429
    code = "spend_cap_exceeded"
    message = "The configured monthly usage budget has been reached."


class VoiceQuotaExceededError(AppError):
    status_code = 429
    code = "voice_quota_exceeded"
    message = "Your daily voice allowance has been used up."


@dataclass(frozen=True)
class TurnCost:
    model: str
    usage: TokenUsage
    cost_usd: float

    def as_dict(self) -> dict[str, object]:
        return {
            **self.usage.as_dict(),
            "model": self.model,
            # Named to make its provenance obvious wherever it is read.
            "estimated_cost_usd": round(self.cost_usd, 6),
        }


class UsageLedger:
    def __init__(self, client: redis.Redis, settings: Settings) -> None:
        self._redis = client
        self._settings = settings

    # --- keys ---------------------------------------------------------------

    @staticmethod
    def _month_key(now: datetime) -> str:
        return f"spend:{now:%Y-%m}"

    @staticmethod
    def _voice_key(student_id: str, now: datetime) -> str:
        return f"voice:{student_id}:{now:%Y-%m-%d}"

    # --- spend --------------------------------------------------------------

    async def monthly_spend_usd(self, *, now: datetime | None = None) -> float:
        raw = await self._redis.get(self._month_key(now or datetime.now(UTC)))
        return (int(raw) / _MICRO) if raw else 0.0

    async def check_spend_cap(self, *, now: datetime | None = None) -> None:
        """Refuse a paid operation once the ceiling is reached.

        Check-then-act, so a burst of concurrent turns can overshoot the cap by roughly the cost
        of the turns already in flight. Bounded and acceptable for a per-month budget; a hard
        guarantee would need a reservation, which would add a round trip to every turn.
        """
        cap = self._settings.monthly_spend_cap_usd
        if cap is None:
            return  # no cap configured — and the app says so at startup rather than implying one
        spent = await self.monthly_spend_usd(now=now)
        if spent >= cap:
            log.warning("cost_guard.cap_reached", spent_usd=round(spent, 4), cap_usd=cap)
            raise SpendCapExceededError

    def price_turn(self, model: str, usage: TokenUsage) -> TurnCost:
        return TurnCost(
            model=model,
            usage=usage,
            cost_usd=estimate_cost_usd(
                model,
                input_tokens=usage.input_tokens,
                output_tokens=usage.output_tokens,
                cache_creation_input_tokens=usage.cache_creation_input_tokens,
                cache_read_input_tokens=usage.cache_read_input_tokens,
            ),
        )

    async def record_turn(self, cost: TurnCost, *, now: datetime | None = None) -> None:
        micros = round(cost.cost_usd * _MICRO)
        if micros <= 0:
            return
        key = self._month_key(now or datetime.now(UTC))
        pipe = self._redis.pipeline()
        pipe.incrby(key, micros)
        pipe.expire(key, _MONTH_TTL_SECONDS)
        await pipe.execute()

    # --- voice minutes ------------------------------------------------------

    async def voice_seconds_used(self, student_id: str, *, now: datetime | None = None) -> int:
        raw = await self._redis.get(self._voice_key(student_id, now or datetime.now(UTC)))
        return int(raw) if raw else 0

    async def check_voice_quota(self, student_id: str, *, now: datetime | None = None) -> None:
        allowance = self._settings.rate_limit_voice_minutes_per_day * 60
        if await self.voice_seconds_used(student_id, now=now) >= allowance:
            raise VoiceQuotaExceededError

    async def record_voice_seconds(
        self, student_id: str, seconds: int, *, now: datetime | None = None
    ) -> int:
        """Add to today's usage and return the new total.

        Called as audio is consumed rather than once at session end, so an abandoned session still
        counts the audio it actually used.
        """
        if seconds <= 0:
            return await self.voice_seconds_used(student_id, now=now)
        key = self._voice_key(student_id, now or datetime.now(UTC))
        pipe = self._redis.pipeline()
        pipe.incrby(key, seconds)
        pipe.expire(key, _DAY_TTL_SECONDS)
        total, _ = await pipe.execute()
        return int(total)
