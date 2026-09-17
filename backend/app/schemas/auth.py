"""Auth request/response models."""

import uuid
from typing import Annotated

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator

# 12 characters rather than 8: this is a single-factor login. Length is the only knob that
# reliably helps, so it is the one we set.
Password = Annotated[str, Field(min_length=12, max_length=128)]


class RegisterRequest(BaseModel):
    email: EmailStr
    password: Password
    display_name: Annotated[str, Field(min_length=1, max_length=120)]
    semester: Annotated[int | None, Field(default=None, ge=1, le=12)]

    @field_validator("display_name")
    @classmethod
    def _strip(cls, v: str) -> str:
        stripped = v.strip()
        if not stripped:
            raise ValueError("display_name must not be blank")
        return stripped


class LoginRequest(BaseModel):
    email: EmailStr
    password: Annotated[str, Field(min_length=1, max_length=128)]


class RefreshRequest(BaseModel):
    refresh_token: Annotated[str, Field(min_length=1, max_length=512)]


class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"  # noqa: S105 - the RFC 6750 scheme name, not a secret
    expires_in: int


class StudentSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    display_name: str
    institution: str | None
    semester: int | None
    preferred_language: str
    consent_audio_retention: bool


class MeResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    email: str
    role: str
    student: StudentSummary | None


class ProfileUpdateRequest(BaseModel):
    display_name: Annotated[str | None, Field(default=None, min_length=1, max_length=120)] = None
    institution: Annotated[str | None, Field(default=None, max_length=200)] = None
    semester: Annotated[int | None, Field(default=None, ge=1, le=12)] = None
    preferred_language: Annotated[str | None, Field(default=None)] = None
    consent_audio_retention: bool | None = None

    @field_validator("preferred_language")
    @classmethod
    def _allowed(cls, v: str | None) -> str | None:
        allowed = {"en", "hi", "hi-Latn", "ta", "auto"}
        if v is not None and v not in allowed:
            raise ValueError(f"preferred_language must be one of {sorted(allowed)}")
        return v
