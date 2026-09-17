"""Conversation session endpoints.

Every route scopes to the authenticated student. `SessionRepository` offers no unscoped lookup,
so an IDOR cannot be written here even by accident (SECURITY.md §3).
"""

import uuid

from fastapi import APIRouter, Depends, Query, status

from app.api.deps import CurrentUserDep, DbDep, rate_limit_ai, rate_limit_authenticated
from app.core.errors import NotFoundError
from app.db.models import SessionStatus
from app.db.repositories.sessions import MessageRepository, SessionRepository
from app.schemas.sessions import (
    MessageResponse,
    PaginatedSessions,
    SessionCreateRequest,
    SessionResponse,
)

router = APIRouter(prefix="/sessions", tags=["sessions"])


@router.post(
    "",
    response_model=SessionResponse,
    status_code=status.HTTP_201_CREATED,
    # Starting a session is the entry point to the paid voice path, so it takes the AI limit
    # class rather than the ordinary authenticated one.
    dependencies=[Depends(rate_limit_ai)],
)
async def create_session(
    payload: SessionCreateRequest, current: CurrentUserDep, db: DbDep
) -> SessionResponse:
    student_id = current.require_student_id()
    row = await SessionRepository(db).create(
        student_id=student_id, transport=payload.transport, client_info=payload.client_info
    )
    return SessionResponse.model_validate(row)


@router.get("", response_model=PaginatedSessions, dependencies=[Depends(rate_limit_authenticated)])
async def list_sessions(
    current: CurrentUserDep,
    db: DbDep,
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
) -> PaginatedSessions:
    student_id = current.require_student_id()
    repo = SessionRepository(db)
    rows = await repo.list_for_student(student_id, limit=limit, offset=offset)
    total = await repo.count_for_student(student_id)
    return PaginatedSessions(items=[SessionResponse.model_validate(r) for r in rows], total=total)


@router.get(
    "/{session_id}",
    response_model=SessionResponse,
    dependencies=[Depends(rate_limit_authenticated)],
)
async def get_session(session_id: uuid.UUID, current: CurrentUserDep, db: DbDep) -> SessionResponse:
    student_id = current.require_student_id()
    row = await SessionRepository(db).get_for_student(session_id, student_id)
    if row is None:
        # 404 for both "absent" and "not yours": distinguishing them confirms the existence of
        # another student's session (API.md § Conventions).
        raise NotFoundError("Session not found.")
    return SessionResponse.model_validate(row)


@router.post(
    "/{session_id}/end",
    response_model=SessionResponse,
    dependencies=[Depends(rate_limit_authenticated)],
)
async def end_session(session_id: uuid.UUID, current: CurrentUserDep, db: DbDep) -> SessionResponse:
    student_id = current.require_student_id()
    repo = SessionRepository(db)
    ended = await repo.end(session_id, student_id, SessionStatus.ENDED)
    row = await repo.get_for_student(session_id, student_id)
    if row is None:
        raise NotFoundError("Session not found.")
    if not ended and row.status is SessionStatus.ACTIVE:  # pragma: no cover - defensive
        raise NotFoundError("Session not found.")
    return SessionResponse.model_validate(row)


@router.get(
    "/{session_id}/messages",
    response_model=list[MessageResponse],
    dependencies=[Depends(rate_limit_authenticated)],
)
async def list_messages(
    session_id: uuid.UUID,
    current: CurrentUserDep,
    db: DbDep,
    limit: int = Query(default=200, ge=1, le=500),
) -> list[MessageResponse]:
    student_id = current.require_student_id()
    # Ownership is proved before any message is read.
    if await SessionRepository(db).get_for_student(session_id, student_id) is None:
        raise NotFoundError("Session not found.")
    rows = await MessageRepository(db).list_for_session(session_id, limit=limit)
    return [MessageResponse.model_validate(r) for r in rows]
