"""Authentication endpoints."""

from fastapi import APIRouter, Depends, Request, status

from app.api.deps import (
    AuthServiceDep,
    CurrentUserDep,
    DbDep,
    rate_limit_anonymous,
    rate_limit_authenticated,
)
from app.db.repositories.users import StudentRepository, UserRepository
from app.schemas.auth import (
    LoginRequest,
    MeResponse,
    ProfileUpdateRequest,
    RefreshRequest,
    RegisterRequest,
    StudentSummary,
    TokenResponse,
)

router = APIRouter(prefix="/auth", tags=["auth"])


def _user_agent(request: Request) -> str | None:
    return request.headers.get("user-agent")


@router.post(
    "/register",
    response_model=TokenResponse,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(rate_limit_anonymous)],
)
async def register(
    payload: RegisterRequest, request: Request, auth: AuthServiceDep
) -> TokenResponse:
    await auth.register(
        email=payload.email,
        password=payload.password,
        display_name=payload.display_name,
        semester=payload.semester,
    )
    access, refresh, expires_in = await auth.login(
        email=payload.email, password=payload.password, user_agent=_user_agent(request)
    )
    return TokenResponse(access_token=access, refresh_token=refresh, expires_in=expires_in)


@router.post("/login", response_model=TokenResponse, dependencies=[Depends(rate_limit_anonymous)])
async def login(payload: LoginRequest, request: Request, auth: AuthServiceDep) -> TokenResponse:
    access, refresh, expires_in = await auth.login(
        email=payload.email, password=payload.password, user_agent=_user_agent(request)
    )
    return TokenResponse(access_token=access, refresh_token=refresh, expires_in=expires_in)


@router.post("/refresh", response_model=TokenResponse, dependencies=[Depends(rate_limit_anonymous)])
async def refresh(payload: RefreshRequest, request: Request, auth: AuthServiceDep) -> TokenResponse:
    access, new_refresh, expires_in = await auth.refresh(
        raw_token=payload.refresh_token, user_agent=_user_agent(request)
    )
    return TokenResponse(access_token=access, refresh_token=new_refresh, expires_in=expires_in)


@router.post(
    "/logout",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[Depends(rate_limit_anonymous)],
)
async def logout(payload: RefreshRequest, auth: AuthServiceDep) -> None:
    await auth.logout(raw_token=payload.refresh_token)


@router.get("/me", response_model=MeResponse, dependencies=[Depends(rate_limit_authenticated)])
async def me(current: CurrentUserDep, db: DbDep) -> MeResponse:
    user = await UserRepository(db).get_by_id(current.user_id)
    assert user is not None  # get_current_user already proved the row exists
    student = await StudentRepository(db).get_by_user_id(current.user_id)
    return MeResponse(
        id=user.id,
        email=str(user.email),
        role=str(user.role),
        student=StudentSummary.model_validate(student) if student else None,
    )


@router.delete(
    "/me",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[Depends(rate_limit_authenticated)],
)
async def delete_account(current: CurrentUserDep, db: DbDep) -> None:
    """Erase the account and all of its data.

    Irreversible and immediate. Everything owned by the user goes by database cascade, so there
    is no list of tables here to fall out of date as later phases add more.
    """
    await UserRepository(db).delete(current.user_id)


@router.patch(
    "/me/profile",
    response_model=StudentSummary,
    dependencies=[Depends(rate_limit_authenticated)],
)
async def update_profile(
    payload: ProfileUpdateRequest,
    current: CurrentUserDep,
    db: DbDep,
) -> StudentSummary:
    student_id = current.require_student_id()
    student = await StudentRepository(db).get_by_id(student_id)
    assert student is not None

    # Only the authenticated student's own row is reachable: student_id comes from the token,
    # never from the payload, so there is nothing to authorize against.
    for field, value in payload.model_dump(exclude_unset=True).items():
        if value is not None:
            setattr(student, field, value)
    await db.flush()
    return StudentSummary.model_validate(student)
