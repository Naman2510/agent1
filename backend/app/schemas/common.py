"""Shared response models."""

from pydantic import BaseModel


class HealthResponse(BaseModel):
    status: str
    environment: str
    version: str


class ReadinessResponse(BaseModel):
    status: str
    database: str
    redis: str


class ErrorDetail(BaseModel):
    code: str
    message: str
    request_id: str | None = None


class ErrorResponse(BaseModel):
    error: ErrorDetail
