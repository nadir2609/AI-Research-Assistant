"""Offline tests for concurrent source orchestration."""

from __future__ import annotations

import asyncio
import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from ai.schemas import Source
from src.concurrency.orchestrator import ResearchOrchestrator
from src.config import Settings
from src.services.external_policy import ExternalCallPolicy


@pytest.fixture
def orchestrator() -> ResearchOrchestrator:
    tmpdir = tempfile.mkdtemp()
    env_file = Path(tmpdir) / ".env"
    env_file.write_text(
        "LLM_PROVIDER=anthropic\n"
        "WEB_SEARCH_PROVIDER=duckduckgo\n"
        "ANTHROPIC_API_KEY=test_key\n"
        "PER_SOURCE_TIMEOUT_SECONDS=0.5\n"
    )
    settings = Settings.from_env(env_file=env_file)
    return ResearchOrchestrator(settings=settings)


def _source(title: str, origin: str) -> Source:
    return Source(
        title=title,
        url="https://example.com/doc",
        snippet="snippet",
        origin=origin,
    )


@pytest.mark.asyncio
async def test_gather_one_failure_degrades(orchestrator: ResearchOrchestrator) -> None:
    wiki_sources = [_source("Wiki", "wikipedia")]
    web_sources = [_source("Web", "web")]

    async def fake_wikipedia(*_args, **_kwargs):
        return wiki_sources

    async def fake_arxiv(*_args, **_kwargs):
        raise RuntimeError("arxiv down")

    async def fake_web(*_args, **_kwargs):
        return web_sources

    with patch.dict(
        "src.concurrency.orchestrator._FETCHERS",
        {
            "wikipedia": fake_wikipedia,
            "arxiv": fake_arxiv,
            "web": fake_web,
        },
    ):
        results = await orchestrator.fetch_sources(
            "test question",
            ["wikipedia", "arxiv", "web"],
        )

    by_type = {r.source_type: r for r in results}
    assert len(by_type["wikipedia"].sources) == 1
    assert len(by_type["web"].sources) == 1
    assert by_type["arxiv"].error is not None
    assert by_type["arxiv"].sources == []


@pytest.mark.asyncio
async def test_respects_source_subset(orchestrator: ResearchOrchestrator) -> None:
    called: list[str] = []

    async def fake_wikipedia(*_args, **_kwargs):
        called.append("wikipedia")
        return [_source("W", "wikipedia")]

    async def fake_web(*_args, **_kwargs):
        called.append("web")
        return [_source("Web", "web")]

    mock_arxiv = AsyncMock()

    with patch.dict(
        "src.concurrency.orchestrator._FETCHERS",
        {
            "wikipedia": fake_wikipedia,
            "arxiv": mock_arxiv,
            "web": fake_web,
        },
    ):
        results = await orchestrator.fetch_sources(
            "subset test",
            ["wikipedia", "web"],
        )

    mock_arxiv.assert_not_called()
    assert set(called) == {"wikipedia", "web"}
    assert len(results) == 2


@pytest.mark.asyncio
async def test_return_exceptions_normalized(orchestrator: ResearchOrchestrator) -> None:
    async def boom(*_args, **_kwargs):
        raise ValueError("unexpected")

    with patch.dict(
        "src.concurrency.orchestrator._FETCHERS",
        {"wikipedia": boom, "arxiv": AsyncMock(), "web": AsyncMock()},
    ):
        results = await orchestrator.fetch_sources("q", ["wikipedia"])

    assert len(results) == 1
    assert results[0].error is not None
    assert results[0].sources == []


@pytest.mark.asyncio
async def test_per_source_timeout(monkeypatch: pytest.MonkeyPatch) -> None:
    # Ensure no earlier test-supplied env vars override the temp .env file.
    monkeypatch.delenv("PER_SOURCE_TIMEOUT_SECONDS", raising=False)
    monkeypatch.delenv("LLM_PROVIDER", raising=False)
    monkeypatch.delenv("WEB_SEARCH_PROVIDER", raising=False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)

    tmpdir = tempfile.mkdtemp()
    env_file = Path(tmpdir) / ".env"
    env_file.write_text(
        "LLM_PROVIDER=anthropic\n"
        "WEB_SEARCH_PROVIDER=duckduckgo\n"
        "ANTHROPIC_API_KEY=test_key\n"
        "PER_SOURCE_TIMEOUT_SECONDS=0.1\n"
    )
    settings = Settings.from_env(env_file=env_file)
    policy = ExternalCallPolicy.from_settings(settings, max_retries=1)
    orchestrator = ResearchOrchestrator(settings=settings, policy=policy)

    async def slow(*_args, **_kwargs):
        await asyncio.sleep(2)
        return []

    with patch.dict(
        "src.concurrency.orchestrator._FETCHERS",
        {"wikipedia": slow, "arxiv": AsyncMock(), "web": AsyncMock()},
    ):
        results = await orchestrator.fetch_sources("q", ["wikipedia"])

    assert results[0].error is not None
    assert "timeout" in (results[0].error or "").lower()
