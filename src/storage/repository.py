import logging
from datetime import datetime, timedelta, timezone
from typing import List, Optional
import json
import asyncpg
from ai.schemas import AnswerWithCitations, Source
from src.storage.cache_keys import canonicalize_query, validate_source_type

logger = logging.getLogger(__name__)


class PostgresRepository:
    """
    Repository layer for storing and retrieving research data in PostgreSQL.

    This class handles:
    - Cached source results in `research_cache`
    - Final answers and citations in `research_history`
    """

    def __init__(
        self,
        pool: asyncpg.Pool,
        *,
        ttl_seconds: int | None = None,
        ttl_hours: int | None = None,
    ):
        """
        Initialize the PostgresRepository.

        Args:
            pool: An asyncpg connection pool for database access.
            ttl_seconds: Cache TTL in seconds (preferred).
            ttl_hours: Deprecated alias; used when ``ttl_seconds`` is omitted.
        """
        self.pool = pool
        if ttl_seconds is not None:
            if ttl_seconds < 1:
                raise ValueError("ttl_seconds must be >= 1")
            self._ttl = timedelta(seconds=ttl_seconds)
        elif ttl_hours is not None:
            if ttl_hours < 1:
                raise ValueError("ttl_hours must be >= 1")
            self._ttl = timedelta(hours=ttl_hours)
        else:
            self._ttl = timedelta(hours=24)

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
<<<<<<< Updated upstream
        query = query.lower().strip()
=======
        validate_source_type(source_type)
        query = canonicalize_query(query)
        if not query:
            return None
        if len(query) > 2000:
            raise ValueError("query too long")
>>>>>>> Stashed changes

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
        if age >= self._ttl:
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
<<<<<<< Updated upstream
        query = query.lower().strip()
        content = json.dumps([source.model_dump() for source in sources])
=======
        validate_source_type(source_type)
        query = canonicalize_query(query)
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
>>>>>>> Stashed changes

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
<<<<<<< Updated upstream
                json.dumps(citations),
=======
                json.dumps(citations),  # <-- SERIALIZE TO JSON STRING
>>>>>>> Stashed changes
            )

        logger.info("Final answer saved to history.")