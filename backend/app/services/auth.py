"""Authentication flows: registration, login, refresh rotation, logout.

The refresh design is the interesting part. Refresh tokens are opaque, single-use, and belong to a
rotation *family*. Presenting a token that has already been used is the signature of a stolen
token, so the entire family is revoked rather than just that token — the legitimate user is logged
out, which is the correct trade when the alternative is leaving an attacker with a valid session.
"""

import uuid
from datetime import UTC, datetime

import structlog
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.errors import (
    AuthenticationError,
    ConflictError,
    InvalidCredentialsError,
)
from app.core.security import (
    PasswordHasherService,
    create_access_token,
    hash_refresh_token,
    new_refresh_token,
)
from app.db.models import RefreshToken, Student, User, UserRole
from app.db.repositories.users import RefreshTokenRepository, StudentRepository, UserRepository

log = structlog.get_logger(__name__)


class AuthService:
    def __init__(
        self,
        session: AsyncSession,
        settings: Settings,
        hasher: PasswordHasherService,
    ) -> None:
        self._session = session
        self._settings = settings
        self._hasher = hasher
        self._users = UserRepository(session)
        self._students = StudentRepository(session)
        self._tokens = RefreshTokenRepository(session)

    # --- registration -------------------------------------------------------

    async def register(
        self, *, email: str, password: str, display_name: str, semester: int | None
    ) -> tuple[User, Student]:
        password_hash = self._hasher.hash(password)
        try:
            user = await self._users.create(email=email, password_hash=password_hash)
            student = await self._students.create(
                user_id=user.id, display_name=display_name, semester=semester
            )
            await self._session.flush()
        except IntegrityError as exc:
            await self._session.rollback()
            # The unique constraint is the only integrity error reachable here; the message stays
            # generic so registration is not an account-existence oracle.
            raise ConflictError("An account with that email already exists.") from exc
        log.info("auth.registered", user_id=str(user.id))
        return user, student

    # --- login --------------------------------------------------------------

    async def login(
        self, *, email: str, password: str, user_agent: str | None
    ) -> tuple[str, str, int]:
        user = await self._users.get_by_email(email)
        if user is None:
            # Hash anyway so a missing account and a wrong password take comparable time.
            self._hasher.hash(password)
            raise InvalidCredentialsError
        if not self._hasher.verify(user.password_hash, password):
            raise InvalidCredentialsError
        if not user.is_active:
            raise AuthenticationError("This account is disabled.")

        if self._hasher.needs_rehash(user.password_hash):
            await self._users.update_password_hash(user.id, self._hasher.hash(password))

        student = await self._students.get_by_user_id(user.id)
        return await self._issue_pair(
            user=user,
            student_id=student.id if student else None,
            family_id=uuid.uuid4(),
            user_agent=user_agent,
        )

    # --- refresh ------------------------------------------------------------

    async def refresh(self, *, raw_token: str, user_agent: str | None) -> tuple[str, str, int]:
        token = await self._tokens.get_by_hash(hash_refresh_token(raw_token))
        if token is None:
            raise AuthenticationError("Refresh token is invalid.")

        if token.revoked_at is not None:
            # Reuse of a rotated token: treat the family as compromised.
            revoked = await self._tokens.revoke_family(token.family_id)
            await self._commit_security_action()
            log.warning(
                "auth.refresh_reuse_detected",
                user_id=str(token.user_id),
                family_id=str(token.family_id),
                revoked_count=revoked,
            )
            raise AuthenticationError("Refresh token has been revoked.")

        if token.expires_at <= datetime.now(UTC):
            await self._tokens.revoke(token.id)
            await self._commit_security_action()
            raise AuthenticationError("Refresh token has expired.")

        user = await self._users.get_by_id(token.user_id)
        if user is None or not user.is_active:
            await self._tokens.revoke_family(token.family_id)
            await self._commit_security_action()
            raise AuthenticationError("Account is unavailable.")

        await self._tokens.revoke(token.id)
        student = await self._students.get_by_user_id(user.id)
        return await self._issue_pair(
            user=user,
            student_id=student.id if student else None,
            family_id=token.family_id,
            user_agent=user_agent,
        )

    # --- logout -------------------------------------------------------------

    async def logout(self, *, raw_token: str) -> None:
        token = await self._tokens.get_by_hash(hash_refresh_token(raw_token))
        if token is None:
            # Idempotent: logging out an unknown token is not an error worth leaking.
            return
        await self._tokens.revoke_family(token.family_id)
        log.info("auth.logout", user_id=str(token.user_id))

    # --- helpers ------------------------------------------------------------

    async def _commit_security_action(self) -> None:
        """Persist a revocation that is about to be followed by an error.

        The request-scoped transaction rolls back on any exception, so a revocation written just
        before raising would be silently discarded — leaving a token we have already decided is
        compromised still valid. These writes are therefore committed on their own. Caught by
        test_refresh_reuse_revokes_the_whole_family.
        """
        await self._session.commit()

    async def _issue_pair(
        self,
        *,
        user: User,
        student_id: uuid.UUID | None,
        family_id: uuid.UUID,
        user_agent: str | None,
    ) -> tuple[str, str, int]:
        access_token, expires_in = create_access_token(
            self._settings, user_id=user.id, role=str(user.role), student_id=student_id
        )
        raw_refresh, refresh_hash = new_refresh_token()
        await self._tokens.create(
            user_id=user.id,
            token_hash=refresh_hash,
            family_id=family_id,
            ttl_seconds=self._settings.refresh_token_ttl_seconds,
            user_agent=user_agent,
        )
        return access_token, raw_refresh, expires_in

    async def promote_to_admin(self, user_id: uuid.UUID) -> None:
        """Used by seeding and tests; there is no HTTP route that grants admin."""
        user = await self._users.get_by_id(user_id)
        if user is None:
            raise AuthenticationError("Unknown user.")
        user.role = UserRole.ADMIN
        await self._session.flush()


__all__ = ["AuthService", "RefreshToken"]
