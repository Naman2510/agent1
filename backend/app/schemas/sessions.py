"""Conversation session schemas."""

import uuid
from datetime import datetime
from typing import Annotated, Any

from pydantic import BaseModel, ConfigDict, Field


class SessionCreateRequest(BaseModel):
    transport: Annotated[str, Field(default="websocket", pattern="^(websocket|text)$")]
    client_info: Annotated[dict[str, Any], Field(default_factory=dict)]


class SessionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    status: str
    transport: str
    started_at: datetime
    ended_at: datetime | None
    turn_count: int


class MessageResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    turn_index: int
    seq: int
    role: str
    content: str
    language: str | None
    was_interrupted: bool
    spoken_prefix_chars: int | None
    latency_ms: dict[str, Any]
    created_at: datetime


class PaginatedSessions(BaseModel):
    items: list[SessionResponse]
    total: int
