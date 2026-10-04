"""`generate_quiz` — the model composes the questions, this tool persists them.

Question ids are assigned here (`q1`, `q2`, ...) rather than trusted from the model, so they are
guaranteed unique within a quiz regardless of what the model supplies.
"""

from __future__ import annotations

import uuid
from typing import Any, Literal

from pydantic import Field

from app.agent.tools.base import ToolContext, ToolInput
from app.db.repositories.study import QuizRepository
from app.providers.llm.base import ToolSpec

GENERATE_QUIZ_SCHEMA: dict[str, object] = {
    "type": "object",
    "properties": {
        "subject": {"type": "string"},
        "topic": {"type": "string"},
        "difficulty": {"type": "string", "enum": ["easy", "medium", "hard"]},
        "language": {"type": "string", "description": "BCP-47-ish code, e.g. 'en', 'hi'."},
        "questions": {
            "type": "array",
            "minItems": 1,
            "maxItems": 20,
            "items": {
                "type": "object",
                "properties": {
                    "prompt": {"type": "string"},
                    "expected": {
                        "type": "string",
                        "description": "The correct answer or a model answer to grade against.",
                    },
                    "rubric": {
                        "type": "string",
                        "description": "How to judge a spoken answer as correct (optional).",
                    },
                    "source_chunk_id": {
                        "type": "string",
                        "description": (
                            "The id of the retrieved chunk this question is grounded in, if any "
                            "(from a prior search_knowledge call). Omit for a question you "
                            "composed from general course knowledge rather than a specific chunk."
                        ),
                    },
                },
                "required": ["prompt", "expected"],
            },
        },
    },
    "required": ["subject", "topic", "difficulty", "questions"],
}


class QuizQuestionInput(ToolInput):
    prompt: str = Field(min_length=1)
    expected: str = Field(min_length=1)
    rubric: str | None = None
    source_chunk_id: str | None = None


class GenerateQuizInput(ToolInput):
    subject: str = Field(min_length=1)
    topic: str = Field(min_length=1)
    difficulty: Literal["easy", "medium", "hard"]
    language: str = "en"
    questions: list[QuizQuestionInput] = Field(min_length=1, max_length=20)


GENERATE_QUIZ_TOOL = ToolSpec(
    name="generate_quiz",
    description=(
        "Save a quiz you have written for this student, grounded in retrieved course material "
        "wherever possible (search_knowledge first). Returns a quiz_id; grade the student's "
        "spoken answers yourself and call update_student_progress with the result."
    ),
    input_schema=GENERATE_QUIZ_SCHEMA,
    strict=True,
)


async def generate_quiz(args: GenerateQuizInput, ctx: ToolContext) -> dict[str, Any]:
    questions: list[dict[str, Any]] = []
    source_chunk_ids: list[uuid.UUID] = []

    for index, question in enumerate(args.questions, start=1):
        chunk_id: uuid.UUID | None = None
        if question.source_chunk_id:
            try:
                chunk_id = uuid.UUID(question.source_chunk_id)
            except ValueError:
                chunk_id = None  # an invalid id is treated as "ungrounded", not a hard failure
            else:
                source_chunk_ids.append(chunk_id)
        questions.append(
            {
                "id": f"q{index}",
                "prompt": question.prompt,
                "expected": question.expected,
                "rubric": question.rubric,
                "source_chunk_id": str(chunk_id) if chunk_id else None,
            }
        )

    quiz = await QuizRepository(ctx.db).create(
        student_id=ctx.student_id,
        session_id=ctx.session_id,
        subject=args.subject,
        topic=args.topic,
        difficulty=args.difficulty,
        language=args.language,
        questions=questions,
        source_chunk_ids=source_chunk_ids,
    )
    ungrounded = sum(1 for q in questions if q["source_chunk_id"] is None)
    return {
        "quiz_id": str(quiz.id),
        "question_count": len(questions),
        "ungrounded_count": ungrounded,
    }
