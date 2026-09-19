"""The `search_knowledge` tool's schema (spec §13, ARCHITECTURE §12).

Only the schema and input model live here — Phase 5's scope is the retrieval pipeline the tool
calls into, not the tool-execution loop itself (ADR-0009's orchestrator, Phase 6). Defining the
contract now means Phase 6 wires a caller around `RagService.search` rather than designing the
interface from scratch under time pressure.

No `student_id` field, on purpose: identity is never a tool argument (ARCHITECTURE §8.4). Filters
are course-material metadata only — nothing here can address another student's data because there
is no student-shaped data behind this tool at all.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from app.providers.llm.base import ToolSpec

SEARCH_KNOWLEDGE_SCHEMA: dict[str, object] = {
    "type": "object",
    "properties": {
        "query": {
            "type": "string",
            "description": "The student's question, in their own words.",
        },
        "subject": {
            "type": "string",
            "description": (
                "Restrict to one subject, e.g. 'Electromagnetic Theory'. "
                "Omit to search all subjects."
            ),
        },
        "topic": {
            "type": "string",
            "description": "Restrict to one topic within a subject, e.g. 'Maxwell's Equations'.",
        },
        "difficulty": {
            "type": "string",
            "enum": ["easy", "medium", "hard"],
            "description": "Restrict to material at this difficulty level.",
        },
    },
    "required": ["query"],
}


class SearchKnowledgeInput(BaseModel):
    """The validated shape of a `search_knowledge` call, for Phase 6's tool wrapper."""

    # extra="forbid": Pydantic's default silently drops unknown fields, which would make a
    # model-supplied student_id (or anything else) disappear quietly instead of failing loudly
    # at the one validation boundary between model output and this tool's execution.
    model_config = ConfigDict(extra="forbid")

    query: str = Field(min_length=1, max_length=500)
    subject: str | None = None
    topic: str | None = None
    difficulty: str | None = Field(default=None, pattern="^(easy|medium|hard)$")


SEARCH_KNOWLEDGE_TOOL = ToolSpec(
    name="search_knowledge",
    description=(
        "Search the student's course material for information relevant to their question. "
        "Use this before answering any question that depends on specific course content — "
        "a formula, a definition, a derivation — rather than answering from memory. "
        "Returns numbered excerpts; cite them as [1], [2], etc. in your answer. "
        "If nothing relevant is found, say so rather than answering from general knowledge."
    ),
    input_schema=SEARCH_KNOWLEDGE_SCHEMA,
    strict=True,
)
