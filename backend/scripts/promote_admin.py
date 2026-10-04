"""Grant the admin role to an existing account.

    python scripts/promote_admin.py someone@example.com

There is deliberately no HTTP route that grants admin (app/services/auth.py): admins are made by
someone with shell access to the deployment. The change applies on the account's next request —
roles are read from the database, not from the access token.
"""

from __future__ import annotations

import asyncio
import sys

from sqlalchemy.ext.asyncio import async_sessionmaker

from app.core.config import get_settings
from app.core.security import PasswordHasherService
from app.db.repositories.users import UserRepository
from app.db.session import create_engine
from app.services.auth import AuthService


async def main(email: str) -> int:
    settings = get_settings()
    engine = create_engine(settings)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async with factory() as session:
            user = await UserRepository(session).get_by_email(email)
            if user is None:
                print(f"no account with email {email!r}", file=sys.stderr)
                return 1
            auth = AuthService(session, settings, PasswordHasherService(settings))
            await auth.promote_to_admin(user.id)
            await session.commit()
    finally:
        await engine.dispose()
    print(f"{email} is now an admin")
    return 0


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print(__doc__.strip(), file=sys.stderr)
        raise SystemExit(2)
    raise SystemExit(asyncio.run(main(sys.argv[1])))
