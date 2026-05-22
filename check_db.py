import asyncio
import asyncpg
import json
import sys
import os

async def main(dsn: str):
    conn = await asyncpg.connect(dsn)
    try:
        print("Connected to:", dsn)
        cols = await conn.fetch(
            "SELECT column_name, data_type FROM information_schema.columns WHERE table_name='research_history';"
        )
        if not cols:
            print("No table 'research_history' found in this database.")
        else:
            print("Columns in research_history:")
            for r in cols:
                print(f"  {r['column_name']}: {r['data_type']}")

        print("\nTesting insert with JSON citations (transaction will be rolled back)...")
        tr = conn.transaction()
        await tr.start()
        try:
            try:
                citations = [{"index": 1, "title": "T", "url": "https://t", "origin": "web"}]
                await conn.execute(
                    "INSERT INTO research_history (question, answer, citations) VALUES ($1, $2, $3)",
                    "py-test-q",
                    "py-test-answer",
                    json.dumps(citations),
                )
                print("Insert executed successfully inside transaction.")
                row = await conn.fetchrow(
                    "SELECT question, answer, citations FROM research_history WHERE question = $1", "py-test-q"
                )
                print("Fetched row (inside transaction):", row)
            except Exception as exc:
                print("Insert failed:", type(exc).__name__, exc)
        finally:
            await tr.rollback()
            print("Transaction rolled back (no persistent change).")
    finally:
        await conn.close()
        print("Connection closed.")

if __name__ == "__main__":
    dsn = sys.argv[1] if len(sys.argv) > 1 else os.getenv("DATABASE_URL")
    if not dsn:
        print("Usage: python check_db.py <DATABASE_URL>  OR set environment var DATABASE_URL")
        sys.exit(1)
    asyncio.run(main(dsn))
