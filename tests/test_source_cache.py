"""Tests for filesystem and tiered (source, query) source caches."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from ai.schemas import Source
from src.storage.cache_keys import cache_file_stem, canonicalize_query
from src.storage.source_cache import (
    FilesystemSourceCache,
    TieredSourceCache,
    build_source_cache,
)


def _sample_source() -> Source:
    return Source(
        title="Example",
        url="https://example.org",
        snippet="snippet",
        origin="web",
    )


def test_canonicalize_query_normalizes_case_whitespace_and_punctuation():
    assert canonicalize_query("  WHAT IS PHOTOSYNTHESIS?  ") == "what is photosynthesis"
    assert canonicalize_query("what is photosynthesis") == "what is photosynthesis"


def test_cache_file_stem_stable_for_equivalent_queries():
    q1 = "WHAT IS AI?"
    q2 = "what is ai"
    assert cache_file_stem("wikipedia", q1) == cache_file_stem("wikipedia", q2)


@pytest.mark.asyncio
async def test_filesystem_cache_miss_then_hit(tmp_path: Path):
    cache = FilesystemSourceCache(tmp_path, ttl_seconds=3600)
    sources = [_sample_source()]

    assert await cache.get("web", "My Query") is None
    await cache.set("web", "My Query", sources)

    hit = await cache.get("web", "MY QUERY???")
    assert hit is not None
    assert len(hit) == 1
    assert hit[0].title == "Example"

    stem = cache_file_stem("web", "my query")
    path = tmp_path / "sources" / "web" / f"{stem}.json"
    assert path.is_file()


@pytest.mark.asyncio
async def test_filesystem_cache_expired_entry_removed(tmp_path: Path):
    import json

    cache = FilesystemSourceCache(tmp_path, ttl_seconds=1)
    stem = cache_file_stem("arxiv", "quantum computing")
    path = tmp_path / "sources" / "arxiv" / f"{stem}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    old_time = (datetime.now(timezone.utc) - timedelta(hours=2)).isoformat()
    path.write_text(
        json.dumps(
            {
                "source_type": "arxiv",
                "query": "quantum computing",
                "created_at": old_time,
                "sources": [_sample_source().model_dump()],
            }
        ),
        encoding="utf-8",
    )

    assert await cache.get("arxiv", "quantum computing") is None
    assert not path.is_file()


@pytest.mark.asyncio
async def test_tiered_cache_prefers_first_backend(tmp_path: Path):
    first = AsyncMock()
    first.get = AsyncMock(return_value=[_sample_source()])
    second = AsyncMock()
    second.get = AsyncMock(return_value=None)

    tiered = TieredSourceCache([first, second])
    hit = await tiered.get("web", "test query")

    assert hit is not None
    first.get.assert_awaited_once()
    second.get.assert_not_awaited()


@pytest.mark.asyncio
async def test_tiered_cache_writes_to_all_backends(tmp_path: Path):
    first = AsyncMock()
    first.get = AsyncMock(return_value=None)
    first.set = AsyncMock()
    second = AsyncMock()
    second.get = AsyncMock(return_value=None)
    second.set = AsyncMock()

    tiered = TieredSourceCache([first, second])
    await tiered.set("web", "test query", [_sample_source()])

    first.set.assert_awaited_once()
    second.set.assert_awaited_once()


@pytest.mark.asyncio
async def test_build_source_cache_filesystem_only_without_repository(tmp_path: Path):
    cache = build_source_cache(cache_dir=tmp_path, ttl_seconds=60, repository=None)
    assert isinstance(cache, FilesystemSourceCache)

    await cache.set("wikipedia", "hello world", [_sample_source()])
    assert await cache.get("wikipedia", "HELLO WORLD!") is not None


@pytest.mark.asyncio
async def test_build_source_cache_tiered_when_repository_provided(tmp_path: Path):
    from src.storage.source_cache import PostgresSourceCache, TieredSourceCache

    repo = AsyncMock()
    repo.get_cached_sources = AsyncMock(return_value=None)
    repo.save_source_cache = AsyncMock()

    cache = build_source_cache(
        cache_dir=tmp_path,
        ttl_seconds=60,
        repository=repo,  # type: ignore[arg-type]
    )
    assert isinstance(cache, TieredSourceCache)
    assert isinstance(cache._backends[0], PostgresSourceCache)
    assert isinstance(cache._backends[1], FilesystemSourceCache)
