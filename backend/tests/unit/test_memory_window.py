"""`SessionWindowCache`: verbatim recent turns plus a rolling summary of what fell out of the
window (ARCHITECTURE §12/§13). Postgres is always the fallback, so what matters here is that a
cache miss, a corrupt entry, or a Redis outage degrade to "nothing cached" rather than raising —
and that the fold accumulates a summary correctly when the window actually overflows.
"""

from __future__ import annotations

import uuid
from typing import Literal

import redis.asyncio as redis_async

from app.providers.base import ProviderUnavailableError
from app.providers.llm.base import TurnMessage
from app.providers.llm.fake import FakeLLMProvider, ScriptedTurn
from app.services.memory_window import SessionWindowCache


def _turn(role: Literal["user", "assistant"], text: str) -> TurnMessage:
    return TurnMessage(role=role, text=text)


class BrokenRedis:
    """Mirrors tests/unit/test_rate_limit.py's BrokenRedis: the minimal stand-in for an outage."""

    async def get(self, _key: str):  # type: ignore[no-untyped-def]
        raise redis_async.ConnectionError("redis is down")

    async def set(self, *_args, **_kwargs):  # type: ignore[no-untyped-def]
        raise redis_async.ConnectionError("redis is down")


async def test_a_fresh_session_has_no_cached_window(redis_client) -> None:  # type: ignore[no-untyped-def]
    cache = SessionWindowCache(redis_client, capacity=20, llm=FakeLLMProvider())
    assert await cache.get(uuid.uuid4()) is None


async def test_record_turn_is_retrievable_in_order(redis_client) -> None:  # type: ignore[no-untyped-def]
    cache = SessionWindowCache(redis_client, capacity=20, llm=FakeLLMProvider())
    session_id = uuid.uuid4()

    await cache.record_turn(
        session_id,
        user_message=_turn("user", "What is KVL?"),
        assistant_message=_turn("assistant", "Sum of loop voltages is zero."),
    )
    window = await cache.get(session_id)

    assert window is not None
    assert [t.text for t in window.turns] == ["What is KVL?", "Sum of loop voltages is zero."]
    assert window.summary is None


async def test_turns_within_capacity_stay_verbatim_with_no_summary(redis_client) -> None:  # type: ignore[no-untyped-def]
    cache = SessionWindowCache(redis_client, capacity=4, llm=FakeLLMProvider())
    session_id = uuid.uuid4()

    for i in range(2):
        await cache.record_turn(
            session_id,
            user_message=_turn("user", f"q{i}"),
            assistant_message=_turn("assistant", f"a{i}"),
        )

    window = await cache.get(session_id)
    assert window is not None
    assert len(window.turns) == 4
    assert window.summary is None


async def test_overflow_is_folded_into_a_new_summary(redis_client) -> None:  # type: ignore[no-untyped-def]
    llm = FakeLLMProvider([ScriptedTurn(text="Covered KVL and KCL.")])
    cache = SessionWindowCache(redis_client, capacity=2, llm=llm)
    session_id = uuid.uuid4()

    # Fills the window exactly (capacity=2 means one user+assistant pair).
    await cache.record_turn(
        session_id, user_message=_turn("user", "q0"), assistant_message=_turn("assistant", "a0")
    )
    # This pair overflows the first: q0/a0 must fold into the summary.
    await cache.record_turn(
        session_id, user_message=_turn("user", "q1"), assistant_message=_turn("assistant", "a1")
    )

    window = await cache.get(session_id)
    assert window is not None
    assert [t.text for t in window.turns] == ["q1", "a1"], "capacity is respected exactly"
    assert window.summary == "Covered KVL and KCL."

    fold_request = llm.last_request
    assert "q0" in fold_request.messages[0].text and "a0" in fold_request.messages[0].text
    assert fold_request.effort.value == "low"


async def test_a_second_overflow_accumulates_onto_the_existing_summary(redis_client) -> None:  # type: ignore[no-untyped-def]
    llm = FakeLLMProvider(
        [ScriptedTurn(text="Covered KVL."), ScriptedTurn(text="Covered KVL and KCL.")]
    )
    cache = SessionWindowCache(redis_client, capacity=2, llm=llm)
    session_id = uuid.uuid4()

    for i in range(3):  # the 2nd and 3rd turns each overflow the window by one pair
        await cache.record_turn(
            session_id,
            user_message=_turn("user", f"q{i}"),
            assistant_message=_turn("assistant", f"a{i}"),
        )

    window = await cache.get(session_id)
    assert window is not None
    assert window.summary == "Covered KVL and KCL."

    second_fold_prompt = llm.requests[-1].messages[0].text
    assert "Summary so far: Covered KVL." in second_fold_prompt


async def test_a_provider_failure_during_fold_keeps_the_existing_summary(redis_client) -> None:  # type: ignore[no-untyped-def]
    error = ProviderUnavailableError("down", provider="fake")
    llm = FakeLLMProvider([ScriptedTurn(raise_error=error)])
    cache = SessionWindowCache(redis_client, capacity=2, llm=llm)
    session_id = uuid.uuid4()

    await cache.record_turn(
        session_id, user_message=_turn("user", "q0"), assistant_message=_turn("assistant", "a0")
    )
    await cache.record_turn(  # triggers the (failing) fold
        session_id, user_message=_turn("user", "q1"), assistant_message=_turn("assistant", "a1")
    )

    window = await cache.get(session_id)
    assert window is not None
    assert window.summary is None  # nothing to keep yet, and nothing raised


async def test_a_redis_outage_on_read_degrades_to_no_window() -> None:
    cache = SessionWindowCache(BrokenRedis(), capacity=20, llm=FakeLLMProvider())  # type: ignore[arg-type]
    assert await cache.get(uuid.uuid4()) is None


async def test_a_redis_outage_on_write_does_not_raise() -> None:
    cache = SessionWindowCache(BrokenRedis(), capacity=20, llm=FakeLLMProvider())  # type: ignore[arg-type]
    await cache.record_turn(
        uuid.uuid4(), user_message=_turn("user", "hi"), assistant_message=_turn("assistant", "hi")
    )  # must not raise


async def test_a_corrupt_cache_entry_degrades_to_no_window(redis_client) -> None:  # type: ignore[no-untyped-def]
    cache = SessionWindowCache(redis_client, capacity=20, llm=FakeLLMProvider())
    session_id = uuid.uuid4()
    await redis_client.set(f"sess:{session_id}:window", "not valid json")
    assert await cache.get(session_id) is None


async def test_a_turn_with_an_unrecognised_role_is_dropped_not_fatal(redis_client) -> None:  # type: ignore[no-untyped-def]
    cache = SessionWindowCache(redis_client, capacity=20, llm=FakeLLMProvider())
    session_id = uuid.uuid4()
    await redis_client.set(
        f"sess:{session_id}:window",
        '{"turns": [{"role": "system", "text": "smuggled"}, '
        '{"role": "user", "text": "hi"}], "summary": null}',
    )
    window = await cache.get(session_id)
    assert window is not None
    assert [t.text for t in window.turns] == ["hi"]
