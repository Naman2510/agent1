"""Input validation for the six Phase 6 tools (search_knowledge's own schema is Phase 5's,
tested in test_rag_tool_spec.py). No database: this is the boundary between model output and a
tool call, testable in isolation from what the tool actually does.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.agent.tools.history import RetrievePreviousConversationInput
from app.agent.tools.progress import GetStudentProgressInput, UpdateStudentProgressInput
from app.agent.tools.quiz import GenerateQuizInput
from app.agent.tools.registry import ALL_TOOLS, DEFAULT_REGISTRY, MUTATING_TOOL_NAMES
from app.agent.tools.study import CreateStudyPlanInput, GetStudyPlanInput

# --- shared identity guarantee -----------------------------------------------


@pytest.mark.parametrize("definition", ALL_TOOLS, ids=lambda d: d.name)
def test_no_tool_input_model_has_a_student_id_field(definition) -> None:  # type: ignore[no-untyped-def]
    assert "student_id" not in definition.input_model.model_fields


@pytest.mark.parametrize("definition", ALL_TOOLS, ids=lambda d: d.name)
def test_every_tool_rejects_an_unexpected_field(definition) -> None:  # type: ignore[no-untyped-def]
    minimal = _minimal_valid_kwargs(definition.name)
    with pytest.raises(ValidationError):
        definition.input_model.model_validate({**minimal, "student_id": "not-allowed"})


def _minimal_valid_kwargs(tool_name: str) -> dict:  # type: ignore[type-arg]
    return {
        "search_knowledge": {"query": "what is kvl"},
        "get_student_progress": {},
        "update_student_progress": {"subject": "EMT", "topic": "KVL", "correct": 1, "total": 2},
        "retrieve_previous_conversation": {},
        "create_study_plan": {
            "title": "t",
            "start_date": "2026-01-01",
            "end_date": "2026-01-02",
            "items": [{"day_index": 0, "subject": "EMT", "topic": "KVL", "activity": "revise"}],
        },
        "get_study_plan": {},
        "generate_quiz": {
            "subject": "EMT",
            "topic": "KVL",
            "difficulty": "easy",
            "questions": [{"prompt": "state KVL", "expected": "sum of voltages is zero"}],
        },
    }[tool_name]


def test_registry_has_exactly_seven_tools_matching_architecture_8_2() -> None:
    assert len(ALL_TOOLS) == 7


def test_mutating_tools_are_exactly_the_three_that_write_data() -> None:
    assert {"update_student_progress", "create_study_plan", "generate_quiz"} == MUTATING_TOOL_NAMES


def test_registry_specs_for_silently_skips_an_unknown_name() -> None:
    specs = DEFAULT_REGISTRY.specs_for(["search_knowledge", "not_a_real_tool"])
    assert [s.name for s in specs] == ["search_knowledge"]


# --- get_student_progress ----------------------------------------------------


def test_get_student_progress_with_no_args_is_valid() -> None:
    parsed = GetStudentProgressInput()
    assert parsed.subject is None


# --- update_student_progress --------------------------------------------------


def test_update_student_progress_rejects_correct_greater_than_total() -> None:
    with pytest.raises(ValidationError):
        UpdateStudentProgressInput(subject="EMT", topic="KVL", correct=5, total=3)


def test_update_student_progress_accepts_correct_equal_to_total() -> None:
    parsed = UpdateStudentProgressInput(subject="EMT", topic="KVL", correct=3, total=3)
    assert parsed.correct == 3


def test_update_student_progress_rejects_zero_total() -> None:
    with pytest.raises(ValidationError):
        UpdateStudentProgressInput(subject="EMT", topic="KVL", correct=0, total=0)


# --- retrieve_previous_conversation -------------------------------------------


def test_retrieve_previous_conversation_keyword_is_optional() -> None:
    parsed = RetrievePreviousConversationInput()
    assert parsed.keyword is None


# --- create_study_plan --------------------------------------------------------


def test_create_study_plan_rejects_end_before_start() -> None:
    with pytest.raises(ValidationError):
        CreateStudyPlanInput(
            title="Revision week",
            start_date="2026-02-10",
            end_date="2026-02-05",
            items=[{"day_index": 0, "subject": "EMT", "topic": "KVL", "activity": "revise"}],
        )


def test_create_study_plan_rejects_an_empty_items_list() -> None:
    with pytest.raises(ValidationError):
        CreateStudyPlanInput(
            title="Revision week", start_date="2026-02-10", end_date="2026-02-12", items=[]
        )


def test_create_study_plan_accepts_end_equal_to_start() -> None:
    parsed = CreateStudyPlanInput(
        title="One day",
        start_date="2026-02-10",
        end_date="2026-02-10",
        items=[{"day_index": 0, "subject": "EMT", "topic": "KVL", "activity": "revise"}],
    )
    assert parsed.end_date == parsed.start_date


def test_get_study_plan_with_no_id_is_valid() -> None:
    assert GetStudyPlanInput().plan_id is None


# --- generate_quiz -------------------------------------------------------------


def test_generate_quiz_rejects_an_invalid_difficulty() -> None:
    with pytest.raises(ValidationError):
        GenerateQuizInput(
            subject="EMT",
            topic="KVL",
            difficulty="impossible",
            questions=[{"prompt": "p", "expected": "e"}],
        )


def test_generate_quiz_source_chunk_id_is_optional() -> None:
    parsed = GenerateQuizInput(
        subject="EMT",
        topic="KVL",
        difficulty="easy",
        questions=[{"prompt": "p", "expected": "e"}],
    )
    assert parsed.questions[0].source_chunk_id is None
