"""The text turn, end to end over SSE.

Uses the scripted LLM double, so these assert the application's behaviour — streaming,
persistence, accounting, authorization — not the model's.
"""

from __future__ import annotations

import json
import uuid

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Message, MessageRole
from app.providers.base import ProviderUnavailableError
from app.providers.llm.base import LLMRequest, TokenUsage, ToolCall
from app.providers.llm.fake import FakeLLMProvider, ScriptedTurn
from app.services.conversation import FAILURE_REPLY, REFUSAL_REPLY


def _parse_sse(body: str) -> list[tuple[str, dict]]:
    events: list[tuple[str, dict]] = []
    for block in body.strip().split("\n\n"):
        if not block.strip():
            continue
        name = ""
        payload = "{}"
        for line in block.splitlines():
            if line.startswith("event: "):
                name = line.removeprefix("event: ")
            elif line.startswith("data: "):
                payload = line.removeprefix("data: ")
        events.append((name, json.loads(payload)))
    return events


async def _session(client: AsyncClient, headers: dict[str, str]) -> str:
    response = await client.post("/sessions", headers=headers, json={"transport": "text"})
    assert response.status_code == 201, response.text
    return response.json()["id"]


async def _turn(
    client: AsyncClient, headers: dict[str, str], session_id: str, text: str
) -> list[tuple[str, dict]]:
    response = await client.post(
        f"/sessions/{session_id}/messages", headers=headers, json={"text": text}
    )
    assert response.status_code == 200, response.text
    assert response.headers["content-type"].startswith("text/event-stream")
    return _parse_sse(response.text)


def _mentor_requests(llm: FakeLLMProvider) -> list[LLMRequest]:
    """The real conversational turns, filtering out every auxiliary LLM call around them.

    Phase 6 puts more than one call on the same shared `FakeLLMProvider`: `IntentGate.classify`
    runs before every real turn, and — off the critical path, in a background task with no fixed
    timing relative to the test's own next `await` — `MemoryExtractor` and the short-term window's
    rolling-summary fold can each add one more. None of their system prompts contain the persona
    text, so filtering on the same "VaaniOS" marker `test_the_request_carries_a_cacheable_persona_
    prefix` checks for the real block isolates the mentor's own requests regardless of how many
    auxiliary calls landed, and regardless of the order background tasks happened to run in.
    """
    return [r for r in llm.requests if r.system and "VaaniOS" in r.system[0].text]


# --- streaming --------------------------------------------------------------


async def test_a_turn_streams_fragments_then_a_summary(
    client: AsyncClient, registered, auth_headers, llm: FakeLLMProvider
) -> None:
    _, _, tokens = await registered()
    headers = auth_headers(tokens)
    session_id = await _session(client, headers)

    events = await _turn(client, headers, session_id, "What is KVL?")

    deltas = [payload["text"] for name, payload in events if name == "delta"]
    assert len(deltas) > 1, "the answer must arrive incrementally, not as one blob"
    assert "".join(deltas) == "This is a fake mentor response."

    name, summary = events[-1]
    assert name == "done"
    assert summary["turn_index"] == 0
    assert summary["stop_reason"] == "end_turn"
    assert summary["interrupted"] is False


async def test_the_turn_reports_latency_and_an_estimated_cost(
    client: AsyncClient, registered, auth_headers
) -> None:
    """Gate 2 requires cost per turn to be recorded, not inferred."""
    _, _, tokens = await registered()
    headers = auth_headers(tokens)
    session_id = await _session(client, headers)

    _, summary = (await _turn(client, headers, session_id, "What is KVL?"))[-1]

    assert summary["latency_ms"]["llm_total_ms"] >= 0
    assert "llm_ttft_ms" in summary["latency_ms"], "time-to-first-token must be measured"
    assert summary["token_usage"]["input_tokens"] == 42
    assert summary["token_usage"]["output_tokens"] == 7
    # The double is priced at zero, so the field is present and truthful rather than invented.
    assert summary["estimated_cost_usd"] == 0.0


# --- persistence ------------------------------------------------------------


async def test_both_messages_are_persisted_with_usage_and_timings(
    client: AsyncClient, registered, auth_headers, db_session: AsyncSession
) -> None:
    _, _, tokens = await registered()
    headers = auth_headers(tokens)
    session_id = await _session(client, headers)
    await _turn(client, headers, session_id, "Kirchhoff ka voltage law samjhao")

    rows = (
        (
            await db_session.execute(
                select(Message)
                .where(Message.session_id == uuid.UUID(session_id))
                .order_by(Message.turn_index, Message.seq)
            )
        )
        .scalars()
        .all()
    )
    assert [r.role for r in rows] == [MessageRole.USER, MessageRole.ASSISTANT]
    assert rows[0].content == "Kirchhoff ka voltage law samjhao"
    assert rows[1].content == "This is a fake mentor response."
    assert rows[1].latency_ms["llm_total_ms"] >= 0
    assert rows[1].token_usage is not None
    assert rows[1].token_usage["model"] == "fake-llm-1"
    assert "estimated_cost_usd" in rows[1].token_usage
    assert rows[1].was_interrupted is False


async def test_history_is_replayed_into_the_next_turn(
    client: AsyncClient, registered, auth_headers, llm: FakeLLMProvider
) -> None:
    _, _, tokens = await registered()
    headers = auth_headers(tokens)
    session_id = await _session(client, headers)

    await _turn(client, headers, session_id, "What is KVL?")
    await _turn(client, headers, session_id, "And KCL?")

    second = _mentor_requests(llm)[1]
    texts = [m.text for m in second.messages]
    assert texts[0] == "What is KVL?"
    assert texts[1] == "This is a fake mentor response."
    assert texts[-1] == "And KCL?", "the new utterance must be last"


async def test_turn_indices_increment(client: AsyncClient, registered, auth_headers) -> None:
    _, _, tokens = await registered()
    headers = auth_headers(tokens)
    session_id = await _session(client, headers)

    first = (await _turn(client, headers, session_id, "one"))[-1][1]
    second = (await _turn(client, headers, session_id, "two"))[-1][1]
    assert (first["turn_index"], second["turn_index"]) == (0, 1)


# --- prompt construction ----------------------------------------------------


async def test_the_request_carries_a_cacheable_persona_prefix(
    client: AsyncClient, registered, auth_headers, llm: FakeLLMProvider
) -> None:
    """Gate 2's cache criterion, at the level this suite can prove: the application asks for a
    breakpoint on stable content and on nothing volatile. Whether the provider then serves a
    cache hit is checked live by scripts/smoke_llm.py."""
    _, _, tokens = await registered()
    headers = auth_headers(tokens)
    session_id = await _session(client, headers)
    await _turn(client, headers, session_id, "What is KVL?")

    request = _mentor_requests(llm)[-1]
    assert request.system[0].cacheable is True
    assert "VaaniOS" in request.system[0].text
    # Nothing per-turn may appear in a cached block.
    for block in request.system:
        if block.cacheable:
            assert "What is KVL?" not in block.text
            assert session_id not in block.text


async def test_the_prompt_prefix_is_byte_identical_across_turns(
    client: AsyncClient, registered, auth_headers, llm: FakeLLMProvider
) -> None:
    """A prefix that differs by even one byte between turns can never produce a cache hit."""
    _, _, tokens = await registered()
    headers = auth_headers(tokens)
    session_id = await _session(client, headers)

    await _turn(client, headers, session_id, "first question")
    await _turn(client, headers, session_id, "second question")

    prefixes = [
        tuple(b.text for b in request.system if b.cacheable) for request in _mentor_requests(llm)
    ]
    assert prefixes[0] == prefixes[1]


async def test_tools_offered_are_narrowed_by_intent_not_offered_unconditionally(
    client: AsyncClient, registered, auth_headers, llm: FakeLLMProvider
) -> None:
    """Phase 6: every real turn now offers *some* tools, gated by IntentGate — never all seven
    unconditionally (ARCHITECTURE §8.2), and never zero either, since an unscripted classification
    here falls back to DEFAULT_INTENT (question), which allows only search_knowledge."""
    _, _, tokens = await registered()
    headers = auth_headers(tokens)
    session_id = await _session(client, headers)
    await _turn(client, headers, session_id, "How am I doing in EMT?")

    offered = {tool.name for tool in _mentor_requests(llm)[-1].tools}
    assert offered == {"search_knowledge"}


async def test_the_configured_effort_and_output_cap_are_applied(
    client: AsyncClient, registered, auth_headers, llm: FakeLLMProvider, settings
) -> None:
    _, _, tokens = await registered()
    headers = auth_headers(tokens)
    session_id = await _session(client, headers)
    await _turn(client, headers, session_id, "What is KVL?")

    request = _mentor_requests(llm)[-1]
    assert str(request.effort) == settings.llm_effort
    assert request.max_output_tokens == settings.llm_max_output_tokens


# --- failure and refusal ----------------------------------------------------


@pytest.mark.parametrize("llm", [FakeLLMProvider([ScriptedTurn(stop_reason="refusal")])])
async def test_a_refusal_produces_something_the_mentor_can_say(
    client: AsyncClient, registered, auth_headers, llm: FakeLLMProvider, db_session: AsyncSession
) -> None:
    """An empty turn would read as the system having hung."""
    _, _, tokens = await registered()
    headers = auth_headers(tokens)
    session_id = await _session(client, headers)

    events = await _turn(client, headers, session_id, "help me cheat in my exam")
    deltas = "".join(p["text"] for n, p in events if n == "delta")
    assert deltas == REFUSAL_REPLY
    assert events[-1][1]["stop_reason"] == "refusal"

    stored = (
        (
            await db_session.execute(
                select(Message).where(
                    Message.session_id == uuid.UUID(session_id),
                    Message.role == MessageRole.ASSISTANT,
                )
            )
        )
        .scalars()
        .one()
    )
    assert stored.content == REFUSAL_REPLY


@pytest.mark.parametrize(
    "llm",
    [
        FakeLLMProvider(
            [ScriptedTurn(raise_error=ProviderUnavailableError("upstream down", provider="fake"))]
        )
    ],
)
async def test_a_provider_outage_degrades_to_a_spoken_apology_and_is_still_recorded(
    client: AsyncClient, registered, auth_headers, db_session: AsyncSession
) -> None:
    _, _, tokens = await registered()
    headers = auth_headers(tokens)
    session_id = await _session(client, headers)

    events = await _turn(client, headers, session_id, "What is KVL?")
    assert "".join(p["text"] for n, p in events if n == "delta") == FAILURE_REPLY

    rows = (
        (
            await db_session.execute(
                select(Message).where(Message.session_id == uuid.UUID(session_id))
            )
        )
        .scalars()
        .all()
    )
    # The user's question is not lost just because the answer failed.
    assert len(rows) == 2


@pytest.mark.parametrize(
    "llm",
    [
        FakeLLMProvider(
            [ScriptedTurn(text="ok", tool_calls=[ToolCall(id="t1", name="ghost", arguments={})])]
        )
    ],
)
async def test_an_unexpected_tool_call_does_not_break_the_turn(
    client: AsyncClient, registered, auth_headers
) -> None:
    """No tools are offered yet, so a tool call would mean the model invented one."""
    _, _, tokens = await registered()
    headers = auth_headers(tokens)
    session_id = await _session(client, headers)
    events = await _turn(client, headers, session_id, "hello")
    assert events[-1][0] == "done"


# --- accounting and authorization ------------------------------------------


async def test_the_spend_cap_refuses_a_turn_before_spending(
    client: AsyncClient, registered, auth_headers, app, redis_client
) -> None:
    """Gate 0 finding M-11: the ceiling must stop work, not merely be reported."""
    from app.services.usage import UsageLedger

    capped = app.state.settings.model_copy(update={"monthly_spend_cap_usd": 0.5})
    ledger = UsageLedger(redis_client, capped)
    app.state.usage_ledger = ledger
    await ledger.record_turn(ledger.price_turn("claude-opus-5", TokenUsage(input_tokens=200_000)))

    _, _, tokens = await registered()
    headers = auth_headers(tokens)
    session_id = await _session(client, headers)

    response = await client.post(
        f"/sessions/{session_id}/messages", headers=headers, json={"text": "hi"}
    )
    events = _parse_sse(response.text)
    assert events[-1][0] == "error"
    assert events[-1][1]["code"] == "spend_cap_exceeded"


async def test_a_turn_cannot_be_posted_to_another_students_session(
    client: AsyncClient, registered, auth_headers
) -> None:
    _, _, alice = await registered("alice")
    _, _, mallory = await registered("mallory")
    session_id = await _session(client, auth_headers(alice))

    response = await client.post(
        f"/sessions/{session_id}/messages",
        headers=auth_headers(mallory),
        json={"text": "whose session is this"},
    )
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "not_found"


async def test_a_blank_or_oversized_utterance_is_rejected(
    client: AsyncClient, registered, auth_headers
) -> None:
    _, _, tokens = await registered()
    headers = auth_headers(tokens)
    session_id = await _session(client, headers)

    blank = await client.post(
        f"/sessions/{session_id}/messages", headers=headers, json={"text": "   "}
    )
    assert blank.status_code == 422

    huge = await client.post(
        f"/sessions/{session_id}/messages", headers=headers, json={"text": "x" * 2001}
    )
    assert huge.status_code == 422


async def test_turns_use_the_ai_rate_limit_class(
    client: AsyncClient, registered, auth_headers, settings
) -> None:
    """A turn costs money, so it must not sit in the generous authenticated-read class."""
    _, _, tokens = await registered()
    headers = auth_headers(tokens)
    session_id = await _session(client, headers)  # this already spends one AI token

    statuses = [
        (
            await client.post(
                f"/sessions/{session_id}/messages", headers=headers, json={"text": "hi"}
            )
        ).status_code
        for _ in range(settings.rate_limit_ai_per_min)
    ]
    assert 429 in statuses
