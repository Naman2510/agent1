"""`get_student_progress` (read-only) and `update_student_progress` (mutating, quiz-evidence path).

Conversational signals about mastery ("I still don't get Maxwell's equations") take a different
path entirely: the async `MemoryExtractor` (ARCHITECTURE §12), at the conversational alpha (0.1),
off the critical path. This tool is the *explicit* path — the model calling it after grading a
quiz answer in conversation — and uses the quiz alpha (0.3), because graded evidence deserves more
trust than an inferred conversational signal.
"""

from __future__ import annotations

from typing import Any

from pydantic import Field, model_validator

from app.agent.tools.base import ToolContext, ToolExecutionError, ToolInput
from app.db.repositories.memory import StudentTopicRepository
from app.providers.llm.base import ToolSpec

QUIZ_EVIDENCE_ALPHA = 0.3

GET_STUDENT_PROGRESS_SCHEMA: dict[str, object] = {
    "type": "object",
    "properties": {
        "subject": {
            "type": "string",
            "description": (
                "Restrict to one subject, e.g. 'Electromagnetic Theory'. Omit for all subjects."
            ),
        },
    },
    "required": [],
}


class GetStudentProgressInput(ToolInput):
    subject: str | None = None


GET_STUDENT_PROGRESS_TOOL = ToolSpec(
    name="get_student_progress",
    description=(
        "Look up the student's own mastery record: per-topic mastery estimates and how much "
        "evidence backs each one. Use this to answer 'how am I doing' questions or before "
        "suggesting what to revise. Never returns another student's data."
    ),
    input_schema=GET_STUDENT_PROGRESS_SCHEMA,
    strict=True,
)


async def get_student_progress(args: GetStudentProgressInput, ctx: ToolContext) -> dict[str, Any]:
    topics = await StudentTopicRepository(ctx.db).list_for_student(
        ctx.student_id, subject=args.subject
    )
    return {
        "topics": [
            {
                "subject": row.subject,
                "topic": row.topic,
                "mastery": round(float(row.mastery), 3),
                "confidence": round(float(row.confidence), 3),
                "evidence_count": row.evidence_count,
            }
            for row in topics
        ]
    }


UPDATE_STUDENT_PROGRESS_SCHEMA: dict[str, object] = {
    "type": "object",
    "properties": {
        "subject": {"type": "string", "description": "The subject the quiz was on."},
        "topic": {"type": "string", "description": "The specific topic the quiz was on."},
        "correct": {
            "type": "integer",
            "minimum": 0,
            "description": "How many questions the student answered correctly.",
        },
        "total": {
            "type": "integer",
            "minimum": 1,
            "description": "Total number of questions in this quiz.",
        },
    },
    "required": ["subject", "topic", "correct", "total"],
}


class UpdateStudentProgressInput(ToolInput):
    subject: str
    topic: str
    correct: int = Field(ge=0)
    total: int = Field(ge=1)

    @model_validator(mode="after")
    def _correct_within_total(self) -> UpdateStudentProgressInput:
        if self.correct > self.total:
            raise ValueError(f"correct ({self.correct}) cannot exceed total ({self.total})")
        return self


UPDATE_STUDENT_PROGRESS_TOOL = ToolSpec(
    name="update_student_progress",
    description=(
        "Record the outcome of a quiz you just graded conversationally, updating the student's "
        "mastery estimate for that topic. Only call this after the student has actually answered "
        "quiz questions you asked — never to record an unverified self-assessment."
    ),
    input_schema=UPDATE_STUDENT_PROGRESS_SCHEMA,
    strict=True,
)


async def update_student_progress(
    args: UpdateStudentProgressInput, ctx: ToolContext
) -> dict[str, Any]:
    if args.correct > args.total:  # pragma: no cover - the input model already rejects this
        raise ToolExecutionError("correct cannot exceed total")

    sample = args.correct / args.total
    row = await StudentTopicRepository(ctx.db).apply_ewma(
        ctx.student_id, args.subject, args.topic, sample=sample, alpha=QUIZ_EVIDENCE_ALPHA
    )
    return {
        "subject": row.subject,
        "topic": row.topic,
        "mastery": round(float(row.mastery), 3),
        "evidence_count": row.evidence_count,
    }
