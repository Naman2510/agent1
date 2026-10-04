"""Drop and recreate the `public` schema of VAANIOS_DATABASE_URL.

Used by the test fixtures to guarantee a database with no history before migrations run.
Refuses to touch anything that is not obviously a test or development database, because the only
thing worse than a flaky test is a test that drops production.
"""

import asyncio
import os
import sys

import asyncpg

SAFE_MARKERS = ("test", "dev", "local")


async def main() -> int:
    url = os.environ.get("VAANIOS_DATABASE_URL")
    if not url:
        print("VAANIOS_DATABASE_URL is not set", file=sys.stderr)
        return 2

    dsn = url.replace("postgresql+asyncpg://", "postgresql://")
    database = dsn.rsplit("/", 1)[-1].split("?")[0]
    if not any(marker in database.lower() for marker in SAFE_MARKERS):
        print(
            f"refusing to reset database {database!r}: its name contains none of {SAFE_MARKERS}",
            file=sys.stderr,
        )
        return 3

    connection = await asyncpg.connect(dsn)
    try:
        await connection.execute("DROP SCHEMA public CASCADE")
        await connection.execute("CREATE SCHEMA public")
    finally:
        await connection.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
