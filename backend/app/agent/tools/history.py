"""`retrieve_previous_conversation` — structured filters plus lexical search over past turns, not
vector memory (ADR-0012's v1 decision)."""

from __future__ import annotations

from typing import Any

from pydantic import Field

from app.agent.tools.base import ToolContext, ToolInput
from app.db.models import MessageRole
from app.db.repositories.sessions import MessageRepository
from app.providers.llm.base import ToolSpec

RETRIEVE_PREVIOUS_CONVERSATION_SCHEMA: dict[str, object] = {
    "type": "object",
    "properties": {
        "keyword": {
            "type": "string",
            "description": (
                "A word or phrase to search for in past turns, e.g. 'Thevenin'. "
                "Omit to get the most recent past turns instead of searching."
            ),
        },
    },
    "required": [],
}


class RetrievePreviousConversationInput(ToolInput):
    keyword: str | None = Field(default=None, min_length=1, max_length=200)


RETRIEVE_PREVIOUS_CONVERSATION_TOOL = ToolSpec(
    name="retrieve_previous_conversation",
    description=(
        "Look up what this student has said or been told in earlier sessions. Use this for "
        "'what did we cover last time' or 'you told me about X before' — never to look up "
        "another student's conversations, which this tool cannot do."
    ),
    input_schema=RETRIEVE_PREVIOUS_CONVERSATION_SCHEMA,
    strict=True,
)

_MAX_RESULTS = 5
_SNIPPET_CHARS = 300


async def retrieve_previous_conversation(
    args: RetrievePreviousConversationInput, ctx: ToolContext
) -> dict[str, Any]:
    rows = await MessageRepository(ctx.db).search_for_student(
        ctx.student_id, keyword=args.keyword, limit=_MAX_RESULTS
    )
    if not rows:
        return {"found": False, "message": "No matching earlier conversation was found."}

    return {
        "found": True,
        "turns": [
            {
                "role": "student" if row.role is MessageRole.USER else "mentor",
                "date": row.created_at.date().isoformat(),
                "excerpt": row.content[:_SNIPPET_CHARS],
            }
            for row in rows
        ],
    }
