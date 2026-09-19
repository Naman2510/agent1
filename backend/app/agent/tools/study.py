"""`create_study_plan` (mutating) and `get_study_plan` (read-only).

The model composes the plan's actual content — which days cover which topics — the same way it
composes prose; these tools persist and retrieve it. Neither tool asks an LLM to generate anything
itself (ADR-0009: a tool returns data or persists it, the orchestrating model does the reasoning).
"""

from __future__ import annotations

import uuid
from datetime import date
from typing import Any

from pydantic import Field, model_validator

from app.agent.tools.base import ToolContext, ToolExecutionError, ToolInput
from app.db.repositories.study import StudyPlanRepository
from app.providers.llm.base import ToolSpec

# --- create_study_plan ------------------------------------------------------

CREATE_STUDY_PLAN_SCHEMA: dict[str, object] = {
    "type": "object",
    "properties": {
        "title": {"type": "string", "description": "A short title for the plan."},
        "goal": {"type": "string", "description": "What the plan is meant to achieve."},
        "start_date": {"type": "string", "description": "ISO date, e.g. '2026-09-20'."},
        "end_date": {"type": "string", "description": "ISO date, e.g. '2026-09-27'."},
        "items": {
            "type": "array",
            "minItems": 1,
            "maxItems": 60,
            "description": "One entry per study activity, in any order.",
            "items": {
                "type": "object",
                "properties": {
                    "day_index": {
                        "type": "integer",
                        "minimum": 0,
                        "description": "0 = start_date, 1 = the day after, and so on.",
                    },
                    "subject": {"type": "string"},
                    "topic": {"type": "string"},
                    "activity": {
                        "type": "string",
                        "description": "What to actually do, e.g. 'Re-derive KVL from scratch'.",
                    },
                    "est_minutes": {"type": "integer", "minimum": 1},
                },
                "required": ["day_index", "subject", "topic", "activity"],
            },
        },
    },
    "required": ["title", "start_date", "end_date", "items"],
}


class StudyPlanItemInput(ToolInput):
    day_index: int = Field(ge=0)
    subject: str = Field(min_length=1)
    topic: str = Field(min_length=1)
    activity: str = Field(min_length=1)
    est_minutes: int | None = Field(default=None, ge=1)


class CreateStudyPlanInput(ToolInput):
    title: str = Field(min_length=1, max_length=200)
    goal: str | None = None
    start_date: date
    end_date: date
    items: list[StudyPlanItemInput] = Field(min_length=1, max_length=60)

    @model_validator(mode="after")
    def _end_after_start(self) -> CreateStudyPlanInput:
        if self.end_date < self.start_date:
            raise ValueError("end_date must not be before start_date")
        return self


CREATE_STUDY_PLAN_TOOL = ToolSpec(
    name="create_study_plan",
    description=(
        "Save a day-by-day study plan you have designed for this student. Ground it in their "
        "actual weak topics (call get_student_progress first) rather than guessing."
    ),
    input_schema=CREATE_STUDY_PLAN_SCHEMA,
    strict=True,
)


async def create_study_plan(args: CreateStudyPlanInput, ctx: ToolContext) -> dict[str, Any]:
    plan = await StudyPlanRepository(ctx.db).create_with_items(
        student_id=ctx.student_id,
        title=args.title,
        goal=args.goal,
        start_date=args.start_date,
        end_date=args.end_date,
        items=[item.model_dump() for item in args.items],
    )
    return {"plan_id": str(plan.id), "title": plan.title, "item_count": len(args.items)}


# --- get_study_plan ----------------------------------------------------------

GET_STUDY_PLAN_SCHEMA: dict[str, object] = {
    "type": "object",
    "properties": {
        "plan_id": {
            "type": "string",
            "description": "A specific plan's id. Omit to get the student's current active plan.",
        },
    },
    "required": [],
}


class GetStudyPlanInput(ToolInput):
    plan_id: str | None = None


GET_STUDY_PLAN_TOOL = ToolSpec(
    name="get_study_plan",
    description="Look up a study plan and its items, including which are already completed.",
    input_schema=GET_STUDY_PLAN_SCHEMA,
    strict=True,
)


async def get_study_plan(args: GetStudyPlanInput, ctx: ToolContext) -> dict[str, Any]:
    repo = StudyPlanRepository(ctx.db)
    if args.plan_id is not None:
        try:
            plan_uuid = uuid.UUID(args.plan_id)
        except ValueError as exc:
            raise ToolExecutionError(f"'{args.plan_id}' is not a valid plan id") from exc
        plan = await repo.get_for_student(plan_uuid, ctx.student_id)
    else:
        plan = await repo.get_active_for_student(ctx.student_id)

    if plan is None:
        return {"found": False, "message": "No matching study plan was found."}

    return {
        "found": True,
        "plan_id": str(plan.id),
        "title": plan.title,
        "goal": plan.goal,
        "status": plan.status.value,
        "start_date": plan.start_date.isoformat(),
        "end_date": plan.end_date.isoformat(),
        "items": [
            {
                "day_index": item.day_index,
                "subject": item.subject,
                "topic": item.topic,
                "activity": item.activity,
                "completed": item.completed_at is not None,
            }
            for item in plan.items
        ],
    }
