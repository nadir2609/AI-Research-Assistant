"""ResearchService integration tests for (source, query) caching."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from ai.schemas import AnswerWithCitations, Source
from src.concurrency.orchestrator import SourceFetchResult
from src.config import Settings
from src.services.research_service import ResearchService
from src.storage.source_cache import FilesystemSourceCache


def _settings(tmp_path: Path) -> Settings:
    return Settings(
        llm_provider="anthropic",
        llm_model="claude-sonnet-4-6",
        web_search_provider="duckduckgo",
        log_level="INFO",
        cache_dir=tmp_path,
        cache_ttl_seconds=3600,
        per_source_timeout_seconds=10.0,
        max_sources_per_query=3,
        max_parallel_external_calls=3,
        external_max_retries=1,
        retry_base_delay_seconds=0.5,
        retry_max_delay_seconds=8.0,
        rate_limit_backoff_seconds=2.0,
        rate_limit_burst=2,
        wikipedia_rps=2.0,
        arxiv_rps=1.0,
        web_rps=1.0,
        llm_rps=1.0,
    )


@pytest.mark.asyncio
async def test_ask_uses_filesystem_cache_on_second_call(tmp_path: Path):
    settings = _settings(tmp_path)
    cache = FilesystemSourceCache(tmp_path, ttl_seconds=3600)
    source = Source(
        title="Cached",
        url="https://example.org",
        snippet="from cache",
        origin="web",
    )

    orchestrator = AsyncMock()
    orchestrator.fetch_sources = AsyncMock(
        return_value=[
            SourceFetchResult(source_type="web", sources=[source]),
        ]
    )

    service = ResearchService(
        settings=settings,
        source_cache=cache,
        orchestrator=orchestrator,
    )

    fake_answer = AnswerWithCitations(
        question="What is AI?",
        answer="AI is artificial intelligence [1].",
        citations=[],
    )

    with patch(
        "src.services.research_service.synthesize",
        return_value=fake_answer,
    ):
        await service.ask("What is AI?", source_names=["web"])
        await service.ask("WHAT IS AI???", source_names=["web"])

    assert orchestrator.fetch_sources.await_count == 1
