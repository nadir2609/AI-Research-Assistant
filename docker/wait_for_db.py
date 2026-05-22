"""Block until PostgreSQL accepts connections (used by Docker entrypoint)."""

from __future__ import annotations

import asyncio
import os
import sys

import asyncpg


async def main() -> None:
    dsn = os.environ.get("DATABASE_URL", "").strip()
    if not dsn:
        return

    max_attempts = int(os.environ.get("DB_WAIT_MAX_ATTEMPTS", "60"))
    delay_seconds = float(os.environ.get("DB_WAIT_DELAY_SECONDS", "1"))

    for attempt in range(1, max_attempts + 1):
        try:
            conn = await asyncpg.connect(dsn, timeout=5)
            await conn.close()
            print(f"PostgreSQL is ready (attempt {attempt}/{max_attempts}).")
            return
        except Exception as exc:
            print(
                f"Waiting for PostgreSQL ({attempt}/{max_attempts}): {exc}",
                flush=True,
            )
            await asyncio.sleep(delay_seconds)

    print("PostgreSQL did not become ready in time.", file=sys.stderr)
    raise SystemExit(1)


if __name__ == "__main__":
    asyncio.run(main())
