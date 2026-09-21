"""IntentGate: parsing a classifier's raw text output, and the allowlist table itself.

The allowlist table is executable spec (ARCHITECTURE §8.2's table, verbatim) — a test asserting it
matches that table exactly is what keeps the doc and the code from drifting apart silently.
"""

from __future__ import annotations

import pytest

from app.agent.intent import DEFAULT_INTENT, INTENT_TOOLS, Intent, IntentGate
from app.providers.base import ProviderUnavailableError
from app.providers.llm.base import Effort, StopReason
from app.providers.llm.fake import FakeLLMProvider, ScriptedTurn


def _gate(text: str, *, stop_reason: StopReason = "end_turn") -> tuple[IntentGate, FakeLLMProvider]:
    llm = FakeLLMProvider([ScriptedTurn(text=text, stop_reason=stop_reason)])
    return IntentGate(llm), llm


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("question", Intent.QUESTION),
        ("doubt", Intent.DOUBT),
        ("quiz_request", Intent.QUIZ_REQUEST),
        ("progress_request", Intent.PROGRESS_REQUEST),
        ("revision_request", Intent.REVISION_REQUEST),
        ("study_plan", Intent.STUDY_PLAN),
        ("clarification", Intent.CLARIFICATION),
        ("casual", Intent.CASUAL),
    ],
)
async def test_every_label_round_trips(raw: str, expected: Intent) -> None:
    gate, _ = _gate(raw)
    assert await gate.classify("anything") is expected


@pytest.mark.parametrize(
    "noisy",
    ["Question.", "QUESTION", "  question  ", "'question'", '"question"'],
)
async def test_classification_is_robust_to_minor_formatting_noise(noisy: str) -> None:
    gate, _ = _gate(noisy)
    assert await gate.classify("anything") is Intent.QUESTION


async def test_study_plan_survives_a_space_instead_of_an_underscore() -> None:
    gate, _ = _gate("study plan")
    assert await gate.classify("anything") is Intent.STUDY_PLAN


async def test_an_unparseable_response_degrades_to_the_default_intent() -> None:
    gate, _ = _gate("I'm not sure how to classify that, sorry!")
    assert await gate.classify("anything") is DEFAULT_INTENT


async def test_a_refusal_degrades_to_the_default_intent_rather_than_raising() -> None:
    gate, _ = _gate("", stop_reason="refusal")
    assert await gate.classify("anything") is DEFAULT_INTENT


async def test_a_provider_failure_degrades_to_the_default_intent_not_a_crash() -> None:
    """This call must never be the reason a whole turn fails — see the module docstring."""
    llm = FakeLLMProvider(
        [ScriptedTurn(raise_error=ProviderUnavailableError("down", provider="fake"))]
    )
    gate = IntentGate(llm)
    assert await gate.classify("anything") is DEFAULT_INTENT


async def test_classification_uses_low_effort_and_a_tiny_output_cap() -> None:
    """This call happens on every turn a tool might be relevant; it must stay cheap."""
    gate, llm = _gate("question")
    await gate.classify("What is KVL?")
    request = llm.last_request
    assert request.effort is Effort.LOW
    assert request.max_output_tokens <= 8


async def test_classification_sends_only_the_utterance_no_tools_offered() -> None:
    """The classifier itself must not be able to call a tool — it has one job."""
    gate, llm = _gate("question")
    await gate.classify("What is KVL?")
    request = llm.last_request
    assert request.tools == ()
    assert [m.text for m in request.messages] == ["What is KVL?"]


# --- the allowlist table itself: executable spec, ARCHITECTURE §8.2 ---------


def test_question_and_doubt_expose_only_search_knowledge() -> None:
    assert INTENT_TOOLS[Intent.QUESTION] == {"search_knowledge"}
    assert INTENT_TOOLS[Intent.DOUBT] == {"search_knowledge"}


def test_quiz_request_exposes_generate_quiz_update_progress_and_search_knowledge() -> None:
    assert INTENT_TOOLS[Intent.QUIZ_REQUEST] == {
        "generate_quiz",
        "update_student_progress",
        "search_knowledge",
    }


def test_progress_request_exposes_progress_and_history_but_not_search() -> None:
    assert INTENT_TOOLS[Intent.PROGRESS_REQUEST] == {
        "get_student_progress",
        "retrieve_previous_conversation",
    }


def test_revision_request_exposes_progress_plan_and_search() -> None:
    assert INTENT_TOOLS[Intent.REVISION_REQUEST] == {
        "get_student_progress",
        "create_study_plan",
        "search_knowledge",
    }


def test_study_plan_intent_exposes_the_three_planning_tools() -> None:
    assert INTENT_TOOLS[Intent.STUDY_PLAN] == {
        "create_study_plan",
        "get_study_plan",
        "get_student_progress",
    }


def test_clarification_and_casual_expose_no_tools_at_all() -> None:
    assert INTENT_TOOLS[Intent.CLARIFICATION] == frozenset()
    assert INTENT_TOOLS[Intent.CASUAL] == frozenset()


def test_every_intent_has_an_allowlist_entry() -> None:
    assert set(INTENT_TOOLS.keys()) == set(Intent)


def test_gate_tools_for_matches_the_table_directly() -> None:
    gate, _ = _gate("question")
    assert gate.tools_for(Intent.STUDY_PLAN) == INTENT_TOOLS[Intent.STUDY_PLAN]
