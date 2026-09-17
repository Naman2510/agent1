"""User, student, and refresh-token persistence.

Authorization lives here as well as in the routes (SECURITY.md §3): every query that touches a
student's data takes the acting student explicitly, so a forgotten route guard cannot expose
another student's rows.
"""

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any, cast

from sqlalchemy import CursorResult, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import RefreshToken, Student, User, UserRole


class UserRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_by_email(self, email: str) -> User | None:
        result = await self._session.execute(select(User).where(User.email == email))
        return result.scalar_one_or_none()

    async def get_by_id(self, user_id: uuid.UUID) -> User | None:
        return await self._session.get(User, user_id)

    async def create(
        self, *, email: str, password_hash: str, role: UserRole = UserRole.STUDENT
    ) -> User:
        user = User(email=email, password_hash=password_hash, role=role)
        self._session.add(user)
        await self._session.flush()
        return user

    async def delete(self, user_id: uuid.UUID) -> bool:
        """Erase the account and, by cascade, every row that belongs to it.

        A hard delete, not a soft one: an erasure request means the data is gone, and a
        `deleted_at` flag would leave transcripts and learning records in place
        (DATA_MODEL.md §7, DATASET.md §5).
        """
        user = await self._session.get(User, user_id)
        if user is None:
            return False
        await self._session.delete(user)
        await self._session.flush()
        return True

    async def update_password_hash(self, user_id: uuid.UUID, password_hash: str) -> None:
        await self._session.execute(
            update(User).where(User.id == user_id).values(password_hash=password_hash)
        )


class StudentRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create(
        self, *, user_id: uuid.UUID, display_name: str, semester: int | None = None
    ) -> Student:
        student = Student(user_id=user_id, display_name=display_name, semester=semester)
        self._session.add(student)
        await self._session.flush()
        return student

    async def get_by_user_id(self, user_id: uuid.UUID) -> Student | None:
        result = await self._session.execute(select(Student).where(Student.user_id == user_id))
        return result.scalar_one_or_none()

    async def get_by_id(self, student_id: uuid.UUID) -> Student | None:
        return await self._session.get(Student, student_id)


class RefreshTokenRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create(
        self,
        *,
        user_id: uuid.UUID,
        token_hash: str,
        family_id: uuid.UUID,
        ttl_seconds: int,
        user_agent: str | None,
    ) -> RefreshToken:
        token = RefreshToken(
            user_id=user_id,
            token_hash=token_hash,
            family_id=family_id,
            expires_at=datetime.now(UTC) + timedelta(seconds=ttl_seconds),
            user_agent=(user_agent or "")[:256] or None,
        )
        self._session.add(token)
        await self._session.flush()
        return token

    async def get_by_hash(self, token_hash: str) -> RefreshToken | None:
        result = await self._session.execute(
            select(RefreshToken).where(RefreshToken.token_hash == token_hash)
        )
        return result.scalar_one_or_none()

    async def revoke(self, token_id: uuid.UUID) -> None:
        await self._session.execute(
            update(RefreshToken)
            .where(RefreshToken.id == token_id, RefreshToken.revoked_at.is_(None))
            .values(revoked_at=datetime.now(UTC))
        )

    async def revoke_family(self, family_id: uuid.UUID) -> int:
        """Revoke every live token in a rotation family. Returns the number revoked."""
        result = await self._session.execute(
            update(RefreshToken)
            .where(RefreshToken.family_id == family_id, RefreshToken.revoked_at.is_(None))
            .values(revoked_at=datetime.now(UTC))
        )
        return cast(CursorResult[Any], result).rowcount or 0

    async def revoke_all_for_user(self, user_id: uuid.UUID) -> int:
        result = await self._session.execute(
            update(RefreshToken)
            .where(RefreshToken.user_id == user_id, RefreshToken.revoked_at.is_(None))
            .values(revoked_at=datetime.now(UTC))
        )
        return cast(CursorResult[Any], result).rowcount or 0
