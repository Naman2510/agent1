"""Text-turn schemas."""

from typing import Annotated, Any

from pydantic import BaseModel, Field, field_validator


class TextTurnRequest(BaseModel):
    # Capped: an utterance is one spoken question, and an unbounded body is an unbounded bill.
    text: Annotated[str, Field(min_length=1, max_length=2000)]

    @field_validator("text")
    @classmethod
    def _not_blank(cls, v: str) -> str:
        stripped = v.strip()
        if not stripped:
            raise ValueError("text must not be blank")
        return stripped


class TurnSummary(BaseModel):
    """Sent as the final SSE event, so a client can show timings and cost for the turn."""

    turn_index: int
    stop_reason: str
    interrupted: bool
    language: str | None
    latency_ms: dict[str, int]
    # Derived from published list prices, so it is labelled an estimate wherever it appears.
    estimated_cost_usd: float
    token_usage: dict[str, Any]
