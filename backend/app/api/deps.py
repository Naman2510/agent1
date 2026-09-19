"""FastAPI dependencies: settings, database session, redis, current user, rate limits."""

import hashlib
import uuid
from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Annotated

import redis.asyncio as redis
from fastapi import Depends, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from app.agent.intent import IntentGate
from app.agent.tools.registry import ToolRegistry
from app.core.config import Settings
from app.core.errors import AuthenticationError, PermissionDeniedError, RateLimitedError
from app.core.rate_limit import LimitClass, RateLimiter
from app.core.security import PasswordHasherService, decode_access_token
from app.db.models import UserRole
from app.db.repositories.memory import StudentProfileRepository
from app.db.repositories.sessions import MessageRepository
from app.db.repositories.users import StudentRepository, UserRepository
from app.db.session import session_scope
from app.providers.embedding.tfidf_svd import TfidfSvdEmbeddingProvider
from app.providers.llm.base import LLMProvider
from app.providers.registry import build_reranker
from app.rag.service import RagService
from app.services.auth import AuthService
from app.services.conversation import ConversationService
from app.services.usage import UsageLedger

# auto_error=False so a missing header raises our own uniform 401 body rather than Starlette's.
_bearer = HTTPBearer(auto_error=False)


def get_app_settings(request: Request) -> Settings:
    """The settings the app was constructed with.

    Deliberately not `get_settings()`: that reads the process environment, so a test (or any
    caller that builds an app with explicit settings) would get a different configuration in its
    routes than the one it wired up — including a different JWT secret.
    """
    settings: Settings = request.app.state.settings
    return settings


SettingsDep = Annotated[Settings, Depends(get_app_settings)]


async def get_db(request: Request) -> AsyncIterator[AsyncSession]:
    async for session in session_scope(request.app.state.session_factory):
        yield session


DbDep = Annotated[AsyncSession, Depends(get_db)]


def get_redis(request: Request) -> redis.Redis:
    client: redis.Redis = request.app.state.redis
    return client


RedisDep = Annotated[redis.Redis, Depends(get_redis)]


def get_hasher(request: Request) -> PasswordHasherService:
    hasher: PasswordHasherService = request.app.state.hasher
    return hasher


def get_rate_limiter(request: Request) -> RateLimiter:
    limiter: RateLimiter = request.app.state.rate_limiter
    return limiter


def get_auth_service(
    db: DbDep,
    settings: SettingsDep,
    hasher: Annotated[PasswordHasherService, Depends(get_hasher)],
) -> AuthService:
    return AuthService(db, settings, hasher)


AuthServiceDep = Annotated[AuthService, Depends(get_auth_service)]


def get_llm(request: Request) -> LLMProvider:
    provider: LLMProvider = request.app.state.llm
    return provider


def get_usage_ledger(request: Request) -> UsageLedger:
    ledger: UsageLedger = request.app.state.usage_ledger
    return ledger


def get_conversation_service(
    request: Request,
    db: DbDep,
    settings: SettingsDep,
) -> ConversationService:
    llm = get_llm(request)
    # The embedder is a shared, process-lifetime fit (app.state.embeddings, set at startup —
    # app/main.py); RagService itself is cheap per-request state around that shared fit and the
    # request's own db session, same as every other per-request repository here.
    embeddings: TfidfSvdEmbeddingProvider = request.app.state.embeddings
    rag = RagService(db, embeddings=embeddings, reranker=build_reranker(settings))
    tool_registry: ToolRegistry = request.app.state.tool_registry
    intent_gate: IntentGate = request.app.state.intent_gate
    return ConversationService(
        llm=llm,
        messages=MessageRepository(db),
        ledger=get_usage_ledger(request),
        settings=settings,
        db=db,
        tool_registry=tool_registry,
        intent_gate=intent_gate,
        rag=rag,
        student_profiles=StudentProfileRepository(db),
    )


ConversationServiceDep = Annotated[ConversationService, Depends(get_conversation_service)]
UsageLedgerDep = Annotated[UsageLedger, Depends(get_usage_ledger)]


@dataclass(frozen=True)
class CurrentUser:
    user_id: uuid.UUID
    role: UserRole
    student_id: uuid.UUID | None

    @property
    def is_admin(self) -> bool:
        return self.role is UserRole.ADMIN

    def require_student_id(self) -> uuid.UUID:
        """The authenticated student's id.

        This is the only source of student identity in the application. Tools and routes never
        accept a student_id from a caller or from model output (ARCHITECTURE §8.4).
        """
        if self.student_id is None:
            raise PermissionDeniedError("This endpoint requires a student account.")
        return self.student_id


async def get_current_user(
    settings: SettingsDep,
    db: DbDep,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)] = None,
) -> CurrentUser:
    if credentials is None or not credentials.credentials:
        raise AuthenticationError
    payload = decode_access_token(settings, credentials.credentials)

    try:
        user_id = uuid.UUID(payload["sub"])
    except (KeyError, ValueError) as exc:
        raise AuthenticationError("Access token is invalid.") from exc

    # The token is not trusted on its own: a disabled or deleted account must stop working
    # immediately rather than at token expiry.
    user = await UserRepository(db).get_by_id(user_id)
    if user is None or not user.is_active:
        raise AuthenticationError("Account is unavailable.")

    student = await StudentRepository(db).get_by_user_id(user_id)
    return CurrentUser(user_id=user.id, role=user.role, student_id=student.id if student else None)


CurrentUserDep = Annotated[CurrentUser, Depends(get_current_user)]


async def require_admin(current: CurrentUserDep) -> CurrentUser:
    if not current.is_admin:
        raise PermissionDeniedError
    return current


AdminDep = Annotated[CurrentUser, Depends(require_admin)]


def _client_identity(request: Request) -> str:
    """Hashed client IP. Raw addresses are personal data and are not stored (SECURITY.md §5)."""
    forwarded = request.headers.get("x-forwarded-for", "")
    ip = (
        forwarded.split(",")[0].strip()
        if forwarded
        else (request.client.host if request.client else "unknown")
    )
    return hashlib.sha256(ip.encode("utf-8")).hexdigest()[:32]


async def _enforce(request: Request, limit_class: LimitClass, identity: str, cost: int = 1) -> None:
    limiter = get_rate_limiter(request)
    decision = await limiter.check(limit_class, identity, cost=cost)
    if not decision.allowed:
        raise RateLimitedError(retry_after=decision.retry_after)


async def rate_limit_anonymous(request: Request) -> None:
    """For unauthenticated endpoints, keyed by hashed IP."""
    await _enforce(request, LimitClass.ANONYMOUS, _client_identity(request))


async def rate_limit_authenticated(request: Request, current: CurrentUserDep) -> None:
    """For ordinary authenticated reads, keyed by user."""
    await _enforce(request, LimitClass.AUTHENTICATED, str(current.user_id))


async def rate_limit_ai(request: Request, current: CurrentUserDep) -> None:
    """For operations that cost money per call (SECURITY.md §4)."""
    await _enforce(request, LimitClass.AI, str(current.user_id))
