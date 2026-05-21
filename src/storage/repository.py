import logging
from datetime import datetime, timedelta, timezone
from typing import List, Optional
import json
import asyncpg
from ai.schemas import AnswerWithCitations, Source

logger = logging.getLogger(__name__)


class PostgresRepository:
    """
    Repository layer for storing and retrieving research data in PostgreSQL.

    This class handles:
    - Cached source results in `research_cache`
    - Final answers and citations in `research_history`
    """

    def __init__(self, pool: asyncpg.Pool, ttl_hours: int = 24):
        """
        Initialize the PostgresRepository.

        Args:
            pool: An asyncpg connection pool for database access.
            ttl_hours: Time-to-live in hours for cached entries. Cache entries
                older than this will be considered expired and ignored.
                Defaults to 24 hours.
        """
        self.pool = pool
        self.ttl_hours = ttl_hours

    async def get_cached_sources(
        self, source_type: str, query: str
    ) -> Optional[List[Source]]:
        """
        Load cached source results for a given source type and query.

        The lookup is case-insensitive in practice because we normalize the query
        to lowercase before querying the database.

        Returns:
            A list of `Source` objects if a valid cache entry exists and is not
            expired; otherwise `None`.
        """
        # Validate inputs
        ALLOWED_SOURCES = {"wikipedia", "arxiv", "web"}
        if source_type not in ALLOWED_SOURCES:
            raise ValueError(f"Unsupported source_type: {source_type}")
        query = (query or "").lower().strip()
        if not query:
            return None
        if len(query) > 2000:
            raise ValueError("query too long")

        async with self.pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                SELECT content, created_at
                FROM research_cache
                WHERE source_type = $1
                  AND query_text = $2
                """,
                source_type,
                query,
            )

        if not row:
            return None

        # Reject expired cache entries.
        age = datetime.now(timezone.utc) - row["created_at"]
        if age >= timedelta(hours=self.ttl_hours):
            logger.info("Cache expired for %s:%s", source_type, query)
            return None

        logger.info("Cache hit for %s:%s", source_type, query)

        # `content` is stored as JSONB in the database, so we convert it back
        # into Python dictionaries and then rebuild `Source` objects.
        return [Source(**item) for item in row["content"]]

    async def save_source_cache(
        self, source_type: str, query: str, sources: List[Source]
    ) -> None:
        """
        Save source results in `research_cache`.

        If a row with the same `(source_type, query_text)` already exists,
        it is updated instead of inserted again.
        """
        # Validate inputs
        ALLOWED_SOURCES = {"wikipedia", "arxiv", "web"}
        if source_type not in ALLOWED_SOURCES:
            raise ValueError(f"Unsupported source_type: {source_type}")
        query = (query or "").lower().strip()
        if not query:
            raise ValueError("query must be non-empty")
        if len(query) > 2000:
            raise ValueError("query too long")

        # Ensure sources are serializable and not excessively large
        content_list = [source.model_dump() for source in sources]
        # pass the list directly so callers (and tests) receive Python structures
        content = content_list
        # approximate size check on serialized JSON to avoid overly large payloads
        if len(json.dumps(content_list)) > 1_000_000:
            raise ValueError("source cache content too large to store")

        async with self.pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO research_cache (source_type, query_text, content, created_at)
                VALUES ($1, $2, $3, CURRENT_TIMESTAMP)
                ON CONFLICT (source_type, query_text)
                DO UPDATE SET
                    content = EXCLUDED.content,
                    created_at = CURRENT_TIMESTAMP
                """,
                source_type,
                query,
                content,
            )

        logger.debug("Saved cache entry for %s:%s", source_type, query)

    async def save_final_answer(
        self, question: str, result: AnswerWithCitations
    ) -> None:
        """
        Save the final generated answer and its citations in `research_history`.

        The citations are stored as JSON, so the full response can be reviewed
        later or displayed in a history screen.
        """
        # Basic validation to avoid inserting pathological values
        if not question or not question.strip():
            raise ValueError("question must be non-empty")
        if len(question) > 5000:
            raise ValueError("question too long")

        citations = [
            {
                "index": citation.index,
                "title": citation.source.title,
                "url": citation.source.url,
                "origin": citation.source.origin,
            }
            for citation in result.citations
        ]

        async with self.pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO research_history (question, answer, citations)
                VALUES ($1, $2, $3)
                """,
                question,
                result.answer,
                citations,
            )

        logger.info("Final answer saved to history.")