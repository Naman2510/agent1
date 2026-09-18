"""Claude adapter (ADR-0008).

Parameter shapes in this area changed recently, so a few choices are deliberate and worth stating
rather than leaving to be "tidied up" later:

* `thinking={"type": "adaptive"}` — `budget_tokens` is rejected on this model. Thinking stays on:
  disabling it risks the model writing a tool call into visible text, which in a voice product
  means the mentor reads a tool call aloud. Depth is tuned with `output_config.effort` instead.
* `thinking.display` is left at its default (omitted). Reasoning is never spoken or shown.
* Tools are declared `strict` with `additionalProperties: false`, so tool arguments are
  schema-valid by construction.
* Cache breakpoints go on the stable system blocks only (ARCHITECTURE §8.5). The adapter reports
  when a breakpoint produced no cache activity, because a prefix below the model's minimum
  cacheable length fails *silently*.
* `stop_reason == "refusal"` is surfaced as a stop reason, never as an exception, so the caller
  can say something useful instead of hanging.

**Verification status:** this adapter has not been exercised against the live API — no credential
was available in the environment where it was written. `scripts/smoke_llm.py` is the live check,
and Gate 2 records this as an open item.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Sequence
from typing import Any

import anthropic
import structlog

from app.providers.base import Capability, ProviderError, ProviderInfo, ProviderUnavailableError
from app.providers.llm.base import (
    LLMProvider,
    LLMRequest,
    StopReason,
    StreamCompleted,
    StreamEvent,
    TextDelta,
    TokenUsage,
    ToolCall,
    ToolCallDelta,
    ToolSpec,
    TurnMessage,
)

log = structlog.get_logger(__name__)

_CAPABILITIES = frozenset(
    {
        Capability.TOOL_CALLING,
        Capability.PROMPT_CACHING,
        Capability.EFFORT_CONTROL,
        Capability.REFUSAL_FALLBACK,
    }
)

_STOP_REASONS: dict[str, StopReason] = {
    "end_turn": "end_turn",
    "tool_use": "tool_use",
    "max_tokens": "max_tokens",
    "refusal": "refusal",
    "stop_sequence": "end_turn",
}


class AnthropicLLMProvider(LLMProvider):
    def __init__(
        self,
        *,
        model: str,
        client: anthropic.AsyncAnthropic | None = None,
        api_key: str | None = None,
        timeout_seconds: float = 30.0,
        max_retries: int = 2,
        refusal_fallback_model: str | None = None,
    ) -> None:
        self._model = model
        self._refusal_fallback_model = refusal_fallback_model
        # Retries are the SDK's (connection errors, 408/409/429/5xx). A voice turn cannot wait
        # long, so the timeout is short and the retry count low.
        self._client = client or anthropic.AsyncAnthropic(
            api_key=api_key, timeout=timeout_seconds, max_retries=max_retries
        )
        # Set once a beta parameter has been rejected, so the fallback path is attempted once per
        # process rather than on every turn.
        self._fallbacks_unavailable = False

    @property
    def info(self) -> ProviderInfo:
        return ProviderInfo(
            kind="llm", name="anthropic", model=self._model, capabilities=_CAPABILITIES
        )

    # --- request construction ---------------------------------------------

    def _system_param(self, request: LLMRequest) -> list[dict[str, Any]]:
        """Build the system parameter, placing a cache breakpoint after each stable block.

        At most four breakpoints exist per request; the assembler keeps well under that, and the
        cap is enforced here so a caller cannot silently lose one.
        """
        blocks: list[dict[str, Any]] = []
        breakpoints = 0
        for block in request.system:
            entry: dict[str, Any] = {"type": "text", "text": block.text}
            if block.cacheable and breakpoints < 4:
                entry["cache_control"] = {"type": "ephemeral"}
                breakpoints += 1
            blocks.append(entry)
        return blocks

    @staticmethod
    def _tool_param(tool: ToolSpec) -> dict[str, Any]:
        schema = dict(tool.input_schema)
        if tool.strict:
            # Required by strict mode; set here so no tool definition can forget it.
            schema.setdefault("additionalProperties", False)
        param: dict[str, Any] = {
            "name": tool.name,
            "description": tool.description,
            "input_schema": schema,
        }
        if tool.strict:
            param["strict"] = True
        return param

    @staticmethod
    def _messages_param(messages: Sequence[TurnMessage]) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        for message in messages:
            content: list[dict[str, Any]] = []
            if message.text:
                content.append({"type": "text", "text": message.text})
            for call in message.tool_calls:
                content.append(
                    {
                        "type": "tool_use",
                        "id": call.id,
                        "name": call.name,
                        "input": call.arguments,
                    }
                )
            if message.tool_results:
                # All tool results for a turn go in ONE user message. Splitting them across
                # messages trains the model to stop making parallel calls.
                content = [
                    {
                        "type": "tool_result",
                        "tool_use_id": result.tool_use_id,
                        "content": result.content,
                        **({"is_error": True} if result.is_error else {}),
                    }
                    for result in message.tool_results
                ]
            if not content:
                continue
            out.append({"role": message.role, "content": content})
        return out

    def _build_params(self, request: LLMRequest) -> dict[str, Any]:
        params: dict[str, Any] = {
            "model": self._model,
            "max_tokens": request.max_output_tokens,
            "system": self._system_param(request),
            "messages": self._messages_param(request.messages),
            "thinking": {"type": "adaptive"},
        }
        if request.effort is not None:
            params["output_config"] = {"effort": str(request.effort)}
        if request.tools:
            # Deterministic order: an unstable tool list is a silent cache invalidator.
            params["tools"] = [
                self._tool_param(tool) for tool in sorted(request.tools, key=lambda t: t.name)
            ]
        return params

    # --- streaming ---------------------------------------------------------

    async def stream(self, request: LLMRequest) -> AsyncIterator[StreamEvent]:
        params = self._build_params(request)
        wants_cache = any(block.cacheable for block in request.system)

        try:
            async for event in self._stream_once(params, wants_cache=wants_cache):
                yield event
        except anthropic.APITimeoutError as exc:
            raise ProviderUnavailableError(
                f"Claude request timed out: {exc}", provider="anthropic"
            ) from exc
        except anthropic.APIConnectionError as exc:
            raise ProviderUnavailableError(
                f"Could not reach Claude: {exc}", provider="anthropic"
            ) from exc
        except anthropic.RateLimitError as exc:
            raise ProviderError(
                "Claude rate limit reached.", provider="anthropic", retryable=True
            ) from exc
        except anthropic.APIStatusError as exc:
            raise ProviderError(
                f"Claude returned {exc.status_code}.",
                provider="anthropic",
                retryable=exc.status_code >= 500,
            ) from exc

    async def _stream_once(
        self, params: dict[str, Any], *, wants_cache: bool
    ) -> AsyncIterator[StreamEvent]:
        use_fallbacks = bool(self._refusal_fallback_model) and not self._fallbacks_unavailable
        manager = self._open_stream(params, use_fallbacks=use_fallbacks)

        if manager is None:  # the beta parameter was rejected; retry plainly
            manager = self._open_stream(params, use_fallbacks=False)
            assert manager is not None

        async with manager as stream:
            async for event in stream:
                if event.type == "content_block_delta" and event.delta.type == "text_delta":
                    yield TextDelta(text=event.delta.text)

            message = await stream.get_final_message()

        usage = _usage_from(message)
        for block in message.content:
            if block.type == "tool_use":
                # Tool inputs are parsed, never string-matched: escaping in the serialised input
                # varies between models.
                yield ToolCallDelta(
                    call=ToolCall(id=block.id, name=block.name, arguments=dict(block.input or {}))
                )

        stop_reason = _STOP_REASONS.get(message.stop_reason or "end_turn", "end_turn")
        if stop_reason == "refusal":
            details = getattr(message, "stop_details", None)
            log.warning(
                "llm.refusal",
                model=message.model,
                category=getattr(details, "category", None),
            )

        ineffective = (
            wants_cache
            and usage.cache_creation_input_tokens == 0
            and usage.cache_read_input_tokens == 0
        )
        if ineffective:
            # Most often a prefix shorter than the model's minimum cacheable length, which
            # produces no error at all — only a bill.
            log.warning("llm.cache_breakpoint_ineffective", model=message.model)

        yield StreamCompleted(
            stop_reason=stop_reason,
            usage=usage,
            model=message.model,
            cache_breakpoint_ineffective=ineffective,
        )

    def _open_stream(self, params: dict[str, Any], *, use_fallbacks: bool) -> Any:
        """Open a streaming request, optionally with server-side refusal fallbacks.

        Returns None if the beta parameter was rejected outright, so the caller can retry without
        it. A policy decline is rare but it must not hang a conversation, and the fallback rescues
        it inside the same call.
        """
        if not use_fallbacks or self._refusal_fallback_model is None:
            return self._client.messages.stream(**params)
        try:
            return self._client.beta.messages.stream(
                **params,
                betas=["server-side-fallback-2026-06-01"],
                fallbacks=[{"model": self._refusal_fallback_model}],
            )
        except TypeError:
            # An SDK that does not know the parameter. Degrade rather than fail the turn.
            self._fallbacks_unavailable = True
            log.warning("llm.refusal_fallback_unsupported", detail="SDK rejected `fallbacks`")
            return None

    async def count_tokens(self, request: LLMRequest) -> int:
        params = self._build_params(request)
        params.pop("max_tokens", None)
        params.pop("output_config", None)
        try:
            result = await self._client.messages.count_tokens(**params)
        except anthropic.APIStatusError as exc:
            raise ProviderError(
                f"Token counting failed: {exc.status_code}", provider="anthropic"
            ) from exc
        return int(result.input_tokens)

    async def aclose(self) -> None:
        await self._client.close()


def _usage_from(message: Any) -> TokenUsage:
    usage = getattr(message, "usage", None)
    if usage is None:  # pragma: no cover - the API always returns usage
        return TokenUsage()
    return TokenUsage(
        input_tokens=int(getattr(usage, "input_tokens", 0) or 0),
        output_tokens=int(getattr(usage, "output_tokens", 0) or 0),
        cache_creation_input_tokens=int(getattr(usage, "cache_creation_input_tokens", 0) or 0),
        cache_read_input_tokens=int(getattr(usage, "cache_read_input_tokens", 0) or 0),
    )
