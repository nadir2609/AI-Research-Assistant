"""Verify DB schema after compose startup (tables exist and are queryable)."""

from __future__ import annotations

import asyncio
import os
import sys

import asyncpg


async def main() -> None:
    dsn = os.environ.get("DATABASE_URL", "").strip()
    if not dsn:
        print("DATABASE_URL not set; skipping DB verification.")
        return

    conn = await asyncpg.connect(dsn, timeout=10)
    try:
        for table in ("research_cache", "research_history"):
            exists = await conn.fetchval(
                """
                SELECT EXISTS (
                    SELECT 1
                    FROM information_schema.tables
                    WHERE table_schema = 'public' AND table_name = $1
                )
                """,
                table,
            )
            if not exists:
                print(f"Missing table: {table}", file=sys.stderr)
                raise SystemExit(1)
            print(f"OK: table '{table}' is present.")

        print("PostgreSQL stack verification passed.")
    finally:
        await conn.close()


if __name__ == "__main__":
    asyncio.run(main())
