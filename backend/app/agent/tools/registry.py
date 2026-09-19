"""The seven tools (ARCHITECTURE §8.2 — corrected from an inherited "eight" miscount that no
document ever actually named an eighth tool for; see the Phase 6 audit), assembled once."""

from __future__ import annotations

from collections.abc import Iterable, Sequence

from app.agent.tools.base import ToolDefinition
from app.agent.tools.history import (
    RETRIEVE_PREVIOUS_CONVERSATION_TOOL,
    RetrievePreviousConversationInput,
    retrieve_previous_conversation,
)
from app.agent.tools.knowledge import SEARCH_KNOWLEDGE_TOOL, search_knowledge
from app.agent.tools.progress import (
    GET_STUDENT_PROGRESS_TOOL,
    UPDATE_STUDENT_PROGRESS_TOOL,
    GetStudentProgressInput,
    UpdateStudentProgressInput,
    get_student_progress,
    update_student_progress,
)
from app.agent.tools.quiz import GENERATE_QUIZ_TOOL, GenerateQuizInput, generate_quiz
from app.agent.tools.study import (
    CREATE_STUDY_PLAN_TOOL,
    GET_STUDY_PLAN_TOOL,
    CreateStudyPlanInput,
    GetStudyPlanInput,
    create_study_plan,
    get_study_plan,
)
from app.providers.llm.base import ToolSpec
from app.rag.tool_spec import SearchKnowledgeInput

ALL_TOOLS: tuple[ToolDefinition, ...] = (
    ToolDefinition(
        spec=SEARCH_KNOWLEDGE_TOOL,
        input_model=SearchKnowledgeInput,
        handler=search_knowledge,
        mutating=False,
    ),
    ToolDefinition(
        spec=GET_STUDENT_PROGRESS_TOOL,
        input_model=GetStudentProgressInput,
        handler=get_student_progress,
        mutating=False,
    ),
    ToolDefinition(
        spec=UPDATE_STUDENT_PROGRESS_TOOL,
        input_model=UpdateStudentProgressInput,
        handler=update_student_progress,
        mutating=True,
    ),
    ToolDefinition(
        spec=RETRIEVE_PREVIOUS_CONVERSATION_TOOL,
        input_model=RetrievePreviousConversationInput,
        handler=retrieve_previous_conversation,
        mutating=False,
    ),
    ToolDefinition(
        spec=CREATE_STUDY_PLAN_TOOL,
        input_model=CreateStudyPlanInput,
        handler=create_study_plan,
        mutating=True,
    ),
    ToolDefinition(
        spec=GET_STUDY_PLAN_TOOL,
        input_model=GetStudyPlanInput,
        handler=get_study_plan,
        mutating=False,
    ),
    ToolDefinition(
        spec=GENERATE_QUIZ_TOOL,
        input_model=GenerateQuizInput,
        handler=generate_quiz,
        mutating=True,
    ),
)

# Excluded from CASUAL/CLARIFICATION and from any intent that has no reason to write data
# (ARCHITECTURE §8.4): a mutating tool is never in an allowlist by accident.
MUTATING_TOOL_NAMES: frozenset[str] = frozenset(t.name for t in ALL_TOOLS if t.mutating)


class ToolRegistry:
    def __init__(self, definitions: Sequence[ToolDefinition] = ALL_TOOLS) -> None:
        names = [d.name for d in definitions]
        if len(names) != len(set(names)):
            raise ValueError(f"duplicate tool name in registry: {names}")
        self._by_name = {d.name: d for d in definitions}

    def get(self, name: str) -> ToolDefinition | None:
        return self._by_name.get(name)

    def specs_for(self, names: Iterable[str]) -> list[ToolSpec]:
        """Specs for an allowlist, silently skipping a name the registry does not know — a typo in
        an `IntentGate` mapping should degrade to fewer tools, not crash the turn."""
        return [self._by_name[name].spec for name in names if name in self._by_name]

    @property
    def all_names(self) -> frozenset[str]:
        return frozenset(self._by_name)


DEFAULT_REGISTRY = ToolRegistry()
