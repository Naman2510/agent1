"""`MemoryExtractor._propose`: parsing the forced tool call, and degrading safely when the model
does not cooperate. None of these paths touch a database — `extract_and_apply` only opens a
session once `_propose` has already returned real signals — so `session_factory` here is one that
would fail loudly if it were ever actually called, making that guarantee part of the test.
"""

from __future__ import annotations

from app.agent.memory_extractor import (
    PROPOSE_MEMORY_DELTAS_TOOL,
    MemoryExtractor,
    ProposedMemoryDeltas,
)
from app.providers.base import ProviderUnavailableError
from app.providers.llm.base import ToolCall
from app.providers.llm.fake import FakeLLMProvider, ScriptedTurn


def _never(*_args: object, **_kwargs: object) -> object:
    raise AssertionError("must not open a database session on this path")


def _extractor(llm: FakeLLMProvider) -> MemoryExtractor:
    return MemoryExtractor(llm, _never)  # type: ignore[arg-type]


async def test_propose_returns_none_when_the_model_never_calls_the_tool() -> None:
    llm = FakeLLMProvider([ScriptedTurn(text="just talking, no tool call")])
    assert await _extractor(llm)._propose("hi", "hello") is None


async def test_propose_returns_none_on_a_provider_failure() -> None:
    error = ProviderUnavailableError("down", provider="fake")
    llm = FakeLLMProvider([ScriptedTurn(raise_error=error)])
    assert await _extractor(llm)._propose("hi", "hello") is None


async def test_propose_rejects_a_malformed_tool_call_rather_than_partially_applying_it() -> None:
    """An out-of-vocabulary `signal` must fail Pydantic validation, not a KeyError later."""
    bad_call = ToolCall(
        id="c1",
        name=PROPOSE_MEMORY_DELTAS_TOOL.name,
        arguments={
            "topic_signals": [
                {
                    "subject": "EMT",
                    "topic": "KVL",
                    "signal": "definitely_mastered_it",  # not in the closed vocabulary
                    "confidence": 0.8,
                    "evidence": "got it right",
                }
            ],
            "preference_signals": [],
        },
    )
    llm = FakeLLMProvider([ScriptedTurn(tool_calls=[bad_call], stop_reason="tool_use")])
    assert await _extractor(llm)._propose("hi", "hello") is None


async def test_propose_ignores_a_call_to_a_different_tool_name() -> None:
    stray_call = ToolCall(id="c1", name="search_knowledge", arguments={"query": "KVL"})
    llm = FakeLLMProvider([ScriptedTurn(tool_calls=[stray_call], stop_reason="tool_use")])
    assert await _extractor(llm)._propose("hi", "hello") is None


async def test_propose_parses_a_well_formed_call() -> None:
    call = ToolCall(
        id="c1",
        name=PROPOSE_MEMORY_DELTAS_TOOL.name,
        arguments={
            "topic_signals": [
                {
                    "subject": "EMT",
                    "topic": "KVL",
                    "signal": "struggled",
                    "confidence": 0.7,
                    "evidence": "asked for a third re-explanation",
                }
            ],
            "preference_signals": [
                {"key": "explanation_style", "value": "analogies", "confidence": 0.6}
            ],
        },
    )
    llm = FakeLLMProvider([ScriptedTurn(tool_calls=[call], stop_reason="tool_use")])

    deltas = await _extractor(llm)._propose("I don't get KVL", "Let me try again with an analogy")

    assert isinstance(deltas, ProposedMemoryDeltas)
    assert deltas.topic_signals[0].signal == "struggled"
    assert deltas.preference_signals[0].value == "analogies"


async def test_propose_forces_the_tool_and_uses_low_effort() -> None:
    call = ToolCall(
        id="c1",
        name=PROPOSE_MEMORY_DELTAS_TOOL.name,
        arguments={"topic_signals": [], "preference_signals": []},
    )
    llm = FakeLLMProvider([ScriptedTurn(tool_calls=[call], stop_reason="tool_use")])

    await _extractor(llm)._propose("hi", "hello")

    request = llm.last_request
    assert request.tool_choice == PROPOSE_MEMORY_DELTAS_TOOL.name
    assert request.effort.value == "low"
