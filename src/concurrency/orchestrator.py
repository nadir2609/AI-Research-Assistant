from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass
from typing import Awaitable, Callable, Iterable

import httpx

from ai.schemas import Source
from ai.sources import fetch_arxiv, fetch_web, fetch_wikipedia
from src.config import Settings
from src.services.external_policy import ExternalCallPolicy

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class SourceFetchResult:
    source_type: str
    sources: list[Source]
    from_cache: bool = False
    elapsed_seconds: float = 0.0
    error: str | None = None


class ResearchOrchestrator:
    def __init__(
        self,
        settings: Settings,
        *,
        policy: ExternalCallPolicy | None = None,
    ) -> None:
        self.settings = settings
        self.policy = policy or ExternalCallPolicy.from_settings(settings)

    async def fetch_sources(
        self,
        query: str,
        source_names: Iterable[str],
    ) -> list[SourceFetchResult]:
        names = list(source_names)
        if not names:
            return []

        headers = {
            "User-Agent": "AI-Research-Assistant/1.0 (+https://example.com)",
        }
        async with httpx.AsyncClient(
            timeout=self.settings.per_source_timeout_seconds,
            follow_redirects=True,
            headers=headers,
        ) as client:
            tasks = [
                self._run_source(source_name, query, client) for source_name in names
            ]
            return await asyncio.gather(*tasks)

    async def _run_source(
        self,
        source_name: str,
        query: str,
        client: httpx.AsyncClient,
    ) -> SourceFetchResult:
        started_at = time.perf_counter()
        operation = self._build_operation(source_name, query, client)

        try:
            sources = await self.policy.call_async(
                source_name,
                lambda: asyncio.wait_for(
                    operation(),
                    timeout=self.settings.per_source_timeout_seconds,
                ),
            )
            elapsed = time.perf_counter() - started_at
            return SourceFetchResult(
                source_type=source_name,
                sources=sources,
                elapsed_seconds=elapsed,
            )
        except asyncio.TimeoutError:
            elapsed = time.perf_counter() - started_at
            return SourceFetchResult(
                source_type=source_name,
                sources=[],
                elapsed_seconds=elapsed,
                error=f"{source_name} timeout",
            )
        except Exception as exc:
            elapsed = time.perf_counter() - started_at
            logger.warning("Source fetch failed source=%s error=%s", source_name, exc)
            return SourceFetchResult(
                source_type=source_name,
                sources=[],
                elapsed_seconds=elapsed,
                error=str(exc),
            )

    def _build_operation(
        self,
        source_name: str,
        query: str,
        client: httpx.AsyncClient,
    ) -> Callable[[], Awaitable[list[Source]]]:
        max_results = self.settings.max_sources_per_query
        timeout = self.settings.per_source_timeout_seconds

        if source_name == "wikipedia":
            return lambda: fetch_wikipedia(
                query,
                max_results=max_results,
                client=client,
                timeout=timeout,
            )
        if source_name == "arxiv":
            return lambda: fetch_arxiv(
                query,
                max_results=max_results,
                client=client,
                timeout=timeout,
            )
        if source_name == "web":
            return lambda: fetch_web(
                query,
                max_results=max_results,
                client=client,
            )
        raise ValueError(f"Unsupported source: {source_name}")
