"""Claude adapter request construction and response mapping.

Driven by a stub client rather than the network: what matters here is the request the adapter
builds and how it interprets a response. The live behaviour is checked separately by
`scripts/smoke_llm.py`, which needs a credential.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import anthropic
import pytest

from app.providers.base import Capability, ProviderError, ProviderUnavailableError
from app.providers.llm.anthropic_provider import AnthropicLLMProvider
from app.providers.llm.base import (
    Effort,
    LLMRequest,
    StreamCompleted,
    SystemBlock,
    TextDelta,
    ToolCall,
    ToolCallDelta,
    ToolResult,
    ToolSpec,
    TurnMessage,
)

# --- stub SDK --------------------------------------------------------------


@dataclass
class _Delta:
    type: str
    text: str = ""


@dataclass
class _Event:
    type: str
    delta: _Delta | None = None


@dataclass
class _Block:
    type: str
    text: str = ""
    id: str = ""
    name: str = ""
    input: dict[str, Any] = field(default_factory=dict)


@dataclass
class _Usage:
    input_tokens: int = 100
    output_tokens: int = 20
    cache_creation_input_tokens: int = 0
    cache_read_input_tokens: int = 0


@dataclass
class _StopDetails:
    type: str = "refusal"
    category: str | None = "cyber"


@dataclass
class _Message:
    content: list[_Block]
    stop_reason: str = "end_turn"
    model: str = "claude-opus-5"
    usage: _Usage = field(default_factory=_Usage)
    stop_details: _StopDetails | None = None


class _Stream:
    def __init__(self, events: list[_Event], message: _Message) -> None:
        self._events = events
        self._message = message

    def __aiter__(self) -> _Stream:
        self._iter = iter(self._events)
        return self

    async def __anext__(self) -> _Event:
        try:
            return next(self._iter)
        except StopIteration:
            raise StopAsyncIteration from None

    async def get_final_message(self) -> _Message:
        return self._message


class _StreamManager:
    def __init__(self, stream: _Stream) -> None:
        self._stream = stream
        self.exited = False

    async def __aenter__(self) -> _Stream:
        return self._stream

    async def __aexit__(self, *_exc: object) -> None:
        self.exited = True


class _Messages:
    def __init__(self, owner: _StubClient, beta: bool) -> None:
        self._owner = owner
        self._beta = beta

    def stream(self, **params: Any) -> _StreamManager:
        if self._beta:
            self._owner.beta_calls.append(params)
        else:
            self._owner.calls.append(params)
        if self._owner.raise_on_stream is not None:
            raise self._owner.raise_on_stream
        manager = _StreamManager(_Stream(self._owner.events, self._owner.message))
        self._owner.managers.append(manager)
        return manager

    async def count_tokens(self, **params: Any) -> Any:
        self._owner.count_calls.append(params)
        return type("R", (), {"input_tokens": 123})()


class _Beta:
    def __init__(self, owner: _StubClient) -> None:
        self.messages = _Messages(owner, beta=True)


class _StubClient:
    def __init__(
        self,
        *,
        events: list[_Event] | None = None,
        message: _Message | None = None,
        raise_on_stream: Exception | None = None,
    ) -> None:
        self.events = events or [_Event("content_block_delta", _Delta("text_delta", "Hello"))]
        self.message = message or _Message(content=[_Block("text", text="Hello")])
        self.raise_on_stream = raise_on_stream
        self.calls: list[dict[str, Any]] = []
        self.beta_calls: list[dict[str, Any]] = []
        self.count_calls: list[dict[str, Any]] = []
        self.managers: list[_StreamManager] = []
        self.messages = _Messages(self, beta=False)
        self.beta = _Beta(self)
        self.closed = False

    async def close(self) -> None:
        self.closed = True


def _provider(client: _StubClient, **kwargs: Any) -> AnthropicLLMProvider:
    kwargs.setdefault("refusal_fallback_model", None)
    return AnthropicLLMProvider(model="claude-opus-5", client=client, **kwargs)  # type: ignore[arg-type]


def _request(**kwargs: Any) -> LLMRequest:
    kwargs.setdefault("system", [SystemBlock(text="You are a mentor.", cacheable=True)])
    kwargs.setdefault("messages", [TurnMessage(role="user", text="What is KVL?")])
    return LLMRequest(**kwargs)


async def _drain(provider: AnthropicLLMProvider, request: LLMRequest) -> list[Any]:
    return [event async for event in provider.stream(request)]


# --- request construction ---------------------------------------------------


async def test_cacheable_system_blocks_get_a_breakpoint_and_others_do_not() -> None:
    client = _StubClient()
    request = _request(
        system=[
            SystemBlock(text="persona", cacheable=True),
            SystemBlock(text="digest", cacheable=True),
            SystemBlock(text="answer in Hindi this turn", cacheable=False),
        ]
    )
    await _drain(_provider(client), request)

    system = client.calls[0]["system"]
    assert [b.get("cache_control") is not None for b in system] == [True, True, False]


async def test_at_most_four_cache_breakpoints_are_emitted() -> None:
    """The API allows four; exceeding it must be clamped here, not discovered as a 400."""
    client = _StubClient()
    request = _request(system=[SystemBlock(text=f"block {i}", cacheable=True) for i in range(7)])
    await _drain(_provider(client), request)

    system = client.calls[0]["system"]
    assert sum(1 for b in system if b.get("cache_control")) == 4
    assert len(system) == 7, "no block may be dropped"


async def test_thinking_is_adaptive_and_budget_tokens_is_never_sent() -> None:
    """`budget_tokens` is rejected on this model; adaptive thinking is the current shape."""
    client = _StubClient()
    await _drain(_provider(client), _request())
    params = client.calls[0]
    assert params["thinking"] == {"type": "adaptive"}
    assert "budget_tokens" not in str(params)


async def test_effort_is_nested_in_output_config() -> None:
    client = _StubClient()
    await _drain(_provider(client), _request(effort=Effort.MEDIUM))
    assert client.calls[0]["output_config"] == {"effort": "medium"}
    assert "effort" not in {k for k in client.calls[0] if k != "output_config"}


async def test_no_output_config_when_effort_is_unset() -> None:
    client = _StubClient()
    await _drain(_provider(client), _request())
    assert "output_config" not in client.calls[0]


async def test_tools_are_strict_with_additional_properties_closed() -> None:
    client = _StubClient()
    tool = ToolSpec(
        name="search_knowledge",
        description="Search course material",
        input_schema={"type": "object", "properties": {"query": {"type": "string"}}},
    )
    await _drain(_provider(client), _request(tools=[tool]))

    sent = client.calls[0]["tools"][0]
    assert sent["strict"] is True
    assert sent["input_schema"]["additionalProperties"] is False
    # The caller's schema object must not be mutated.
    assert "additionalProperties" not in tool.input_schema


async def test_tools_are_sent_in_a_deterministic_order() -> None:
    """An unstable tool list silently invalidates the prompt cache on every request."""
    client = _StubClient()
    tools = [
        ToolSpec(name="z_tool", description="z", input_schema={"type": "object"}),
        ToolSpec(name="a_tool", description="a", input_schema={"type": "object"}),
        ToolSpec(name="m_tool", description="m", input_schema={"type": "object"}),
    ]
    await _drain(_provider(client), _request(tools=tools))
    assert [t["name"] for t in client.calls[0]["tools"]] == ["a_tool", "m_tool", "z_tool"]


async def test_parallel_tool_results_are_sent_in_one_user_message() -> None:
    """Splitting them across messages trains the model to stop calling tools in parallel."""
    client = _StubClient()
    history = [
        TurnMessage(role="user", text="How am I doing?"),
        TurnMessage(
            role="assistant",
            tool_calls=[
                ToolCall(id="t1", name="get_student_progress", arguments={}),
                ToolCall(id="t2", name="retrieve_previous_conversation", arguments={}),
            ],
        ),
        TurnMessage(
            role="user",
            tool_results=[
                ToolResult(tool_use_id="t1", content="mastery 0.4"),
                ToolResult(tool_use_id="t2", content="discussed KVL"),
            ],
        ),
    ]
    await _drain(_provider(client), _request(messages=history))

    messages = client.calls[0]["messages"]
    result_messages = [
        m for m in messages if any(b.get("type") == "tool_result" for b in m["content"])
    ]
    assert len(result_messages) == 1
    assert len(result_messages[0]["content"]) == 2


async def test_tool_errors_are_marked_as_errors() -> None:
    client = _StubClient()
    history = [
        TurnMessage(
            role="user",
            tool_results=[ToolResult(tool_use_id="t1", content="timed out", is_error=True)],
        )
    ]
    await _drain(_provider(client), _request(messages=history))
    block = client.calls[0]["messages"][0]["content"][0]
    assert block["is_error"] is True


# --- response mapping -------------------------------------------------------


async def test_text_deltas_stream_then_completion_is_last() -> None:
    client = _StubClient(
        events=[
            _Event("content_block_delta", _Delta("text_delta", "Kirchhoff ")),
            _Event("content_block_delta", _Delta("text_delta", "ka law")),
        ]
    )
    events = await _drain(_provider(client), _request())
    assert [e.text for e in events if isinstance(e, TextDelta)] == ["Kirchhoff ", "ka law"]
    assert isinstance(events[-1], StreamCompleted)


async def test_thinking_deltas_are_not_streamed_to_the_caller() -> None:
    """Reasoning is never spoken. A thinking delta reaching the TTS path would be audible."""
    client = _StubClient(
        events=[
            _Event("content_block_delta", _Delta("thinking_delta", "let me think")),
            _Event("content_block_delta", _Delta("text_delta", "The answer")),
        ]
    )
    events = await _drain(_provider(client), _request())
    assert [e.text for e in events if isinstance(e, TextDelta)] == ["The answer"]


async def test_tool_calls_are_emitted_with_parsed_arguments() -> None:
    client = _StubClient(
        message=_Message(
            content=[_Block("tool_use", id="t1", name="search_knowledge", input={"query": "KVL"})],
            stop_reason="tool_use",
        )
    )
    events = await _drain(_provider(client), _request())
    calls = [e.call for e in events if isinstance(e, ToolCallDelta)]
    assert calls == [ToolCall(id="t1", name="search_knowledge", arguments={"query": "KVL"})]
    assert events[-1].stop_reason == "tool_use"  # type: ignore[union-attr]


async def test_usage_is_mapped_including_cache_fields() -> None:
    client = _StubClient(
        message=_Message(
            content=[_Block("text", text="hi")],
            usage=_Usage(
                input_tokens=10,
                output_tokens=5,
                cache_creation_input_tokens=1000,
                cache_read_input_tokens=2000,
            ),
        )
    )
    completed = (await _drain(_provider(client), _request()))[-1]
    assert isinstance(completed, StreamCompleted)
    assert completed.usage.input_tokens == 10
    assert completed.usage.cache_read_input_tokens == 2000
    assert completed.usage.total_input_tokens == 3010


async def test_a_requested_breakpoint_with_no_cache_activity_is_reported() -> None:
    """A prefix below the model's minimum cacheable length fails silently — surface it."""
    client = _StubClient(message=_Message(content=[_Block("text", text="hi")], usage=_Usage()))
    completed = (await _drain(_provider(client), _request()))[-1]
    assert isinstance(completed, StreamCompleted)
    assert completed.cache_breakpoint_ineffective is True


async def test_cache_activity_means_the_breakpoint_worked() -> None:
    client = _StubClient(
        message=_Message(
            content=[_Block("text", text="hi")],
            usage=_Usage(cache_read_input_tokens=900),
        )
    )
    completed = (await _drain(_provider(client), _request()))[-1]
    assert completed.cache_breakpoint_ineffective is False  # type: ignore[union-attr]


async def test_no_cache_warning_when_no_breakpoint_was_requested() -> None:
    client = _StubClient()
    request = _request(system=[SystemBlock(text="persona", cacheable=False)])
    completed = (await _drain(_provider(client), request))[-1]
    assert completed.cache_breakpoint_ineffective is False  # type: ignore[union-attr]


async def test_a_refusal_is_a_stop_reason_not_an_exception() -> None:
    """A decline must let the caller say something; raising would hang the conversation."""
    client = _StubClient(
        message=_Message(
            content=[], stop_reason="refusal", stop_details=_StopDetails(category="cyber")
        )
    )
    events = await _drain(_provider(client), _request())
    assert events[-1].stop_reason == "refusal"  # type: ignore[union-attr]


async def test_max_tokens_is_surfaced() -> None:
    client = _StubClient(
        message=_Message(content=[_Block("text", text="trunc")], stop_reason="max_tokens")
    )
    events = await _drain(_provider(client), _request())
    assert events[-1].stop_reason == "max_tokens"  # type: ignore[union-attr]


# --- errors and lifecycle ---------------------------------------------------


async def test_timeout_becomes_a_retryable_provider_error() -> None:
    client = _StubClient(raise_on_stream=anthropic.APITimeoutError(request=None))  # type: ignore[arg-type]
    with pytest.raises(ProviderUnavailableError) as exc:
        await _drain(_provider(client), _request())
    assert exc.value.retryable is True
    assert exc.value.provider == "anthropic"


async def test_rate_limit_is_retryable_and_does_not_leak_the_upstream_body() -> None:
    error = anthropic.RateLimitError(
        "rate limited", response=_FakeResponse(429), body={"secret": "internal detail"}
    )
    client = _StubClient(raise_on_stream=error)
    with pytest.raises(ProviderError) as exc:
        await _drain(_provider(client), _request())
    assert exc.value.retryable is True
    assert "internal detail" not in str(exc.value)


async def test_a_server_error_is_retryable_and_a_client_error_is_not() -> None:
    server = anthropic.APIStatusError("boom", response=_FakeResponse(503), body=None)
    with pytest.raises(ProviderError) as exc:
        await _drain(_provider(_StubClient(raise_on_stream=server)), _request())
    assert exc.value.retryable is True

    client_error = anthropic.APIStatusError("bad", response=_FakeResponse(400), body=None)
    with pytest.raises(ProviderError) as exc2:
        await _drain(_provider(_StubClient(raise_on_stream=client_error)), _request())
    assert exc2.value.retryable is False


async def test_refusal_fallback_uses_the_beta_endpoint_when_configured() -> None:
    client = _StubClient()
    provider = _provider(client, refusal_fallback_model="claude-opus-4-8")
    await _drain(provider, _request())

    assert client.beta_calls, "the beta endpoint should carry the fallbacks parameter"
    params = client.beta_calls[0]
    assert params["fallbacks"] == [{"model": "claude-opus-4-8"}]
    assert params["betas"] == ["server-side-fallback-2026-06-01"]


async def test_without_a_fallback_model_the_plain_endpoint_is_used() -> None:
    client = _StubClient()
    await _drain(_provider(client), _request())
    assert client.calls and not client.beta_calls


async def test_the_stream_context_is_always_exited() -> None:
    """Leaking the context would leak a connection per turn."""
    client = _StubClient()
    await _drain(_provider(client), _request())
    assert client.managers[0].exited is True


async def test_capabilities_are_declared() -> None:
    provider = _provider(_StubClient())
    assert provider.info.supports(Capability.TOOL_CALLING)
    assert provider.info.supports(Capability.PROMPT_CACHING)
    assert provider.info.model == "claude-opus-5"
    assert provider.info.name == "anthropic"


async def test_token_counting_uses_the_provider_and_drops_generation_params() -> None:
    client = _StubClient()
    provider = _provider(client)
    assert await provider.count_tokens(_request(effort=Effort.LOW)) == 123
    params = client.count_calls[0]
    assert "max_tokens" not in params
    assert "output_config" not in params


async def test_close_closes_the_client() -> None:
    client = _StubClient()
    await _provider(client).aclose()
    assert client.closed is True


class _FakeResponse:
    """Minimal stand-in for an httpx response, for constructing SDK errors."""

    def __init__(self, status_code: int) -> None:
        self.status_code = status_code
        self.headers: dict[str, str] = {}
        self.request = None
