"""The tool contract every tool in `app/agent/tools/` shares (ARCHITECTURE §8.3-8.4).

Two guarantees live here, not per-tool:

1. **No tool input model can carry identity.** `ToolInput.model_config` forbids extra fields, so a
   model-supplied `student_id` (or anything else not in a tool's own schema) is rejected rather
   than silently dropped (the gap Phase 5's D5-07 closed for `search_knowledge`; every tool gets
   it from birth here instead of needing its own fix later).
2. **A handler receives identity from `ToolContext`, never from its validated arguments.** There is
   no code path by which a tool's Pydantic input model could even have a `student_id` field to read
   from — the authority boundary is structural, not a check someone could forget.
"""

from __future__ import annotations

import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel, ConfigDict
from sqlalchemy.ext.asyncio import AsyncSession

from app.providers.llm.base import ToolSpec
from app.rag.retrieve import RetrievedChunk
from app.rag.service import RagService


class ToolInput(BaseModel):
    """Base for every tool's input model. See module docstring, guarantee 1."""

    model_config = ConfigDict(extra="forbid")


class ToolExecutionError(Exception):
    """Raised by a handler for an expected, nameable failure (no active plan, quiz not found).

    Caught by the executor and turned into an `is_error=True` tool result with this message, so
    the mentor can say something useful ("I couldn't find an active study plan") instead of the
    turn failing outright. Reserve this for conditions a handler anticipates; let anything else
    propagate as a real bug.
    """


@dataclass(frozen=True)
class ToolContext:
    """What a handler is allowed to know about who is asking — never what the model said.

    `student_id` and `session_id` come from the authenticated session the orchestrator is already
    running under; no handler parameter accepts either from tool arguments (ARCHITECTURE §8.4).
    """

    student_id: uuid.UUID
    session_id: uuid.UUID
    turn_index: int
    db: AsyncSession
    rag: RagService
    # Shared across every tool call in one turn, so a second `search_knowledge` call continues
    # citation numbering ([3], [4]...) instead of restarting at [1] and colliding with the first
    # call's refs. The field is reassignable-looking only because the dataclass is frozen; handlers
    # mutate the dict in place (`ctx.citation_sources.update(...)`), they never replace it.
    citation_sources: dict[str, RetrievedChunk]


ToolHandler = Callable[[Any, ToolContext], Awaitable[dict[str, Any]]]


@dataclass(frozen=True)
class ToolDefinition:
    """One tool's full contract: how it is described to the model, how its arguments are
    validated, what runs, and whether it is allowed to mutate anything."""

    spec: ToolSpec
    input_model: type[ToolInput]
    handler: ToolHandler
    mutating: bool = False
    timeout_seconds: float = 2.0

    @property
    def name(self) -> str:
        return self.spec.name
