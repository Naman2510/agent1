"""The `search_knowledge` tool contract (spec §13): schema and input validation only.

No execution-loop tests here — wiring this schema to `RagService.search` is Phase 6's scope
(see the module docstring in `app.rag.tool_spec`). What this file guards is the contract Phase 6
will build against: the schema shape, and the guarantee that identity never enters through it.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.rag.tool_spec import (
    SEARCH_KNOWLEDGE_SCHEMA,
    SEARCH_KNOWLEDGE_TOOL,
    SearchKnowledgeInput,
)


def test_tool_is_named_and_strict() -> None:
    assert SEARCH_KNOWLEDGE_TOOL.name == "search_knowledge"
    assert SEARCH_KNOWLEDGE_TOOL.strict is True
    assert SEARCH_KNOWLEDGE_TOOL.input_schema is SEARCH_KNOWLEDGE_SCHEMA


def test_only_query_is_required() -> None:
    assert SEARCH_KNOWLEDGE_SCHEMA["required"] == ["query"]


def test_schema_exposes_exactly_the_documented_filters() -> None:
    properties = SEARCH_KNOWLEDGE_SCHEMA["properties"]
    assert set(properties) == {"query", "subject", "topic", "difficulty"}


def test_no_student_id_field_can_reach_the_model() -> None:
    """ARCHITECTURE §8.4: identity is never a tool argument. A `student_id` slipping into this
    schema would let the model claim to search on another student's behalf."""
    assert "student_id" not in SEARCH_KNOWLEDGE_SCHEMA["properties"]
    assert "student_id" not in SearchKnowledgeInput.model_fields


def test_difficulty_enum_is_the_three_course_levels() -> None:
    assert SEARCH_KNOWLEDGE_SCHEMA["properties"]["difficulty"]["enum"] == [
        "easy",
        "medium",
        "hard",
    ]


def test_a_query_only_input_is_valid_with_filters_defaulting_to_none() -> None:
    parsed = SearchKnowledgeInput(query="what does KVL state?")
    assert parsed.query == "what does KVL state?"
    assert parsed.subject is None
    assert parsed.topic is None
    assert parsed.difficulty is None


def test_all_filters_can_be_set_together() -> None:
    parsed = SearchKnowledgeInput(
        query="Maxwell's equations",
        subject="Electromagnetic Theory",
        topic="Maxwell's Equations",
        difficulty="medium",
    )
    assert parsed.subject == "Electromagnetic Theory"
    assert parsed.topic == "Maxwell's Equations"
    assert parsed.difficulty == "medium"


def test_an_empty_query_is_rejected() -> None:
    with pytest.raises(ValidationError):
        SearchKnowledgeInput(query="")


def test_an_overlong_query_is_rejected() -> None:
    with pytest.raises(ValidationError):
        SearchKnowledgeInput(query="a" * 501)


def test_a_query_at_the_length_limit_is_accepted() -> None:
    parsed = SearchKnowledgeInput(query="a" * 500)
    assert len(parsed.query) == 500


@pytest.mark.parametrize("difficulty", ["easy", "medium", "hard"])
def test_each_valid_difficulty_level_is_accepted(difficulty: str) -> None:
    parsed = SearchKnowledgeInput(query="q", difficulty=difficulty)
    assert parsed.difficulty == difficulty


def test_an_invalid_difficulty_level_is_rejected() -> None:
    """Guards against a model hallucinating a level like 'impossible' or 'expert' that the
    retrieval pipeline's own difficulty column (easy/medium/hard, DB check constraint) can't use."""
    with pytest.raises(ValidationError):
        SearchKnowledgeInput(query="q", difficulty="impossible")


def test_an_unknown_field_is_rejected_not_silently_dropped() -> None:
    with pytest.raises(ValidationError):
        SearchKnowledgeInput(query="q", student_id="should-not-be-settable")
