<<<<<<< Updated upstream
=======
"""Concurrent source fetching for the research pipeline.

Owns asyncio.gather, shared httpx client, per-source timeouts, and retries
via ExternalCallPolicy. Business logic (cache, synthesis) lives in ResearchService.
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass

import httpx

from ai.schemas import Source
from ai.sources import fetch_arxiv, fetch_web, fetch_wikipedia
from src.config import Settings
from src.services.external_policy import ExternalCallPolicy

logger = logging.getLogger(__name__)

_FETCHERS: dict[str, Callable[..., Awaitable[list[Source]]]] = {
    "wikipedia": fetch_wikipedia,
    "arxiv": fetch_arxiv,
    "web": fetch_web,
}


@dataclass(frozen=True, slots=True)
class SourceFetchResult:
    """Result of one source fetch attempt."""

    source_type: str
    sources: list[Source]
    from_cache: bool = False
    error: str | None = None
    elapsed_seconds: float = 0.0


class ResearchOrchestrator:
    """Parallel fetch orchestration with per-source timeouts and graceful degradation."""

    def __init__(
        self,
        *,
        settings: Settings,
        policy: ExternalCallPolicy | None = None,
    ) -> None:
        self.settings = settings
        self.policy = policy or ExternalCallPolicy.from_settings(settings)
        self.timeout_seconds = settings.per_source_timeout_seconds

    async def fetch_sources(
        self,
        question: str,
        source_names: list[str],
    ) -> list[SourceFetchResult]:
        """Fetch all named sources in parallel via asyncio.gather."""
        timeout = self.settings.per_source_timeout_seconds
        headers = {"User-Agent": "Research-Assistant/1.0 (+https://github.com/nadir2609/AI-Research-Assistant)"}
        async with httpx.AsyncClient(timeout=timeout, headers=headers) as client:
            tasks = [
                self._fetch_one_live(source_type, question, client)
                for source_type in source_names
            ]
            results = await asyncio.gather(*tasks, return_exceptions=True)

        normalized: list[SourceFetchResult] = []
        for source_type, result in zip(source_names, results, strict=True):
            if isinstance(result, SourceFetchResult):
                normalized.append(result)
                continue

            logger.exception(
                "Unexpected source task failure source=%s error=%s",
                source_type,
                result,
            )
            normalized.append(
                SourceFetchResult(
                    source_type=source_type,
                    sources=[],
                    error=str(result),
                )
            )

        return normalized

    async def run_source(
        self,
        source_name: str,
        operation: Callable[[], Awaitable[list[Source]]],
    ) -> SourceFetchResult:
        """Run one source operation with retries, rate limits, and timeout."""
        started_at = time.perf_counter()

        try:
            sources = await self.policy.call_async(
                source_name,
                operation,
            )
            elapsed = time.perf_counter() - started_at
            return SourceFetchResult(
                source_type=source_name,
                sources=sources,
                elapsed_seconds=elapsed,
            )

        except (TimeoutError, asyncio.TimeoutError):
            elapsed = time.perf_counter() - started_at
            error = f"{source_name} timeout"
            logger.warning("Source fetch failed: %s", error)
            return SourceFetchResult(
                source_type=source_name,
                sources=[],
                error=error,
                elapsed_seconds=elapsed,
            )

        except Exception as exc:
            elapsed = time.perf_counter() - started_at
            logger.warning("Source fetch failed: %s", exc)
            return SourceFetchResult(
                source_type=source_name,
                sources=[],
                error=str(exc),
                elapsed_seconds=elapsed,
            )

    async def _fetch_one_live(
        self,
        source_type: str,
        question: str,
        client: httpx.AsyncClient,
    ) -> SourceFetchResult:
        fetcher = _get_fetcher(source_type)

        async def operation() -> list[Source]:
            return await self._fetch_with_timeout(fetcher, question, client)

        result = await self.run_source(source_type, operation)
        if result.error is None:
            logger.info(
                "Fetched source=%s count=%d elapsed=%.3fs",
                source_type,
                len(result.sources),
                result.elapsed_seconds,
            )
        return result

    async def _fetch_with_timeout(
        self,
        fetcher: Callable[..., Awaitable[list[Source]]],
        question: str,
        client: httpx.AsyncClient,
    ) -> list[Source]:
        timeout = self.settings.per_source_timeout_seconds
        return await asyncio.wait_for(
            fetcher(
                question,
                max_results=self.settings.max_sources_per_query,
                client=client,
            ),
            timeout=timeout,
        )


def _get_fetcher(source_type: str) -> Callable[..., Awaitable[list[Source]]]:
    fetcher = _FETCHERS.get(source_type)
    if fetcher is None:
        raise ValueError(f"Unsupported source type: {source_type!r}")
    return fetcher
>>>>>>> Stashed changes
