"""
tests/test_storage_repository.py

Unit tests for src.storage.repository.PostgresRepository.

These tests are offline: they mock the asyncpg pool and connection so no
database is required.

They use pytest and pytest-asyncio and Python's unittest.mock.AsyncMock.
"""

from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, Mock

import pytest

from ai.schemas import AnswerWithCitations, Citation, Source
from src.storage.repository import PostgresRepository


def _make_mock_pool_and_conn(row_to_return=None):
    """
    Helper to create a mocked asyncpg.Pool whose .acquire() is an async
    context manager returning a mocked connection object.
    The mocked connection will have:
      - fetchrow(...) -> AsyncMock returning row_to_return
      - execute(...) -> AsyncMock

    Returns: (mock_pool, mock_conn)
    """
    # Mocked connection
    mock_conn = AsyncMock()
    mock_conn.fetchrow = AsyncMock(return_value=row_to_return)
    mock_conn.execute = AsyncMock(return_value=None)

    # Async context manager that yields mock_conn
    mock_acm = AsyncMock()
    mock_acm.__aenter__.return_value = mock_conn
    mock_acm.__aexit__.return_value = None

    # Mocked pool
    mock_pool = Mock()
    mock_pool.acquire.return_value = mock_acm

    return mock_pool, mock_conn


@pytest.mark.asyncio
async def test_get_cached_sources_cache_hit_returns_sources():
    # Arrange
    src_obj = Source(
        title="Example Title",
        url="https://example.org",
        snippet="An example snippet",
        origin="web",
    )
    content = [src_obj.model_dump()]  # what repository expects from DB JSONB
    recent_time = datetime.now(timezone.utc)
    row = {"content": content, "created_at": recent_time}

    mock_pool, mock_conn = _make_mock_pool_and_conn(row_to_return=row)
    repo = PostgresRepository(pool=mock_pool, ttl_hours=24)

    # Act
    result = await repo.get_cached_sources("web", "Example Query")

    # Assert
    assert result is not None
    assert isinstance(result, list)
    assert len(result) == 1
    assert isinstance(result[0], Source)
    assert result[0].title == src_obj.title
    # Ensure fetchrow was called with expected SQL parameters (source_type, query)
    # The first positional arg is the SQL string; then source_type and query
    mock_conn.fetchrow.assert_awaited()
    _, called_source_type, called_query = mock_conn.fetchrow.call_args[0]
    assert called_source_type == "web"
    assert called_query == "example query"  # repository lowercases the query


@pytest.mark.asyncio
async def test_get_cached_sources_expired_returns_none():
    # Arrange: created_at older than ttl_hours (set ttl_hours=1, created_at is 2 hours ago)
    old_time = datetime.now(timezone.utc) - timedelta(hours=2)
    row = {"content": [{"title": "t", "url": "u", "snippet": "s", "origin": "web"}], "created_at": old_time}

    mock_pool, mock_conn = _make_mock_pool_and_conn(row_to_return=row)
    repo = PostgresRepository(pool=mock_pool, ttl_hours=1)

    # Act
    result = await repo.get_cached_sources("web", "Some Query")

    # Assert
    assert result is None
    mock_conn.fetchrow.assert_awaited()


@pytest.mark.asyncio
async def test_save_source_cache_calls_execute_with_serialized_content():
    # Arrange
    src1 = Source(title="T1", url="https://example.com/1", snippet="s1", origin="web")
    src2 = Source(title="T2", url="https://example.com/2", snippet="s2", origin="wikipedia")
    content_expected = [src1.model_dump(), src2.model_dump()]

    # No fetchrow needed for save, but prepare pool/conn to capture execute calls
    mock_pool, mock_conn = _make_mock_pool_and_conn(row_to_return=None)
    repo = PostgresRepository(pool=mock_pool, ttl_hours=24)

    # Act
    await repo.save_source_cache("web", "My Query", [src1, src2])

    # Assert execute was awaited and the parameters passed include expected content
    mock_conn.execute.assert_awaited()
    call_args = mock_conn.execute.call_args[0]  # positional args
    # call_args[1] is source_type, call_args[2] is normalized query, call_args[3] is content
    sql_text = call_args[0]
    assert "INSERT INTO research_cache" in sql_text or "ON CONFLICT" in sql_text
    assert call_args[1] == "web"
    assert call_args[2] == "my query"  # repository lowercases the query
    # the content parameter should be the list of dicts we expect
    assert call_args[3] == content_expected


@pytest.mark.asyncio
async def test_save_final_answer_inserts_history_row():
    # Arrange - create AnswerWithCitations with a single citation
    s = Source(title="S", url="https://s", snippet="sn", origin="web")
    citation = Citation(index=1, source=s)
    answer = AnswerWithCitations(question="Q", answer="An answer [1]", citations=[citation])

    mock_pool, mock_conn = _make_mock_pool_and_conn(row_to_return=None)
    repo = PostgresRepository(pool=mock_pool, ttl_hours=24)

    # Act
    await repo.save_final_answer("Q", answer)

    # Assert
    mock_conn.execute.assert_awaited()
    call_args = mock_conn.execute.call_args[0]
    sql_text = call_args[0]
    # SQL should be an INSERT into research_history
    assert "INSERT INTO research_history" in sql_text
    # ensure parameters include question, answer, citations-list
    assert call_args[1] == "Q"
    assert call_args[2] == "An answer [1]"
    # citations parameter should be a list of flattened dicts
    assert isinstance(call_args[3], list)
    assert call_args[3] == [
        {"index": 1, "title": s.title, "url": s.url, "origin": s.origin}
    ]