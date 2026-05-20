import asyncio
import time
from typing import Awaitable, Callable

from ai.schemas import Source
from ai.sources import (
    fetch_arxiv,
    fetch_web,
    fetch_wikipedia,
)
from src.services.external_policy import ExternalCallPolicy


class SourceResult:

    def __init__(
        self,
        source_name: str,
        sources: list[Source],
        success: bool,
        elapsed_seconds: float,
        error: str | None = None,
    ):

        self.source_name = source_name
        self.sources = sources
        self.success = success
        self.elapsed_seconds = elapsed_seconds
        self.error = error


class ResearchOrchestrator:

    def __init__(
        self,
        timeout_seconds: int = 10,
        policy: ExternalCallPolicy | None = None,
    ):

        self.timeout_seconds = timeout_seconds
        self.policy = policy or ExternalCallPolicy.defaults()

    async def run_source(
        self,
        source_name: str,
        operation: Callable[[], Awaitable[list[Source]]],
    ) -> SourceResult:

        started_at = time.perf_counter()

        try:

            result = await self.policy.call_async(
                source_name,
                lambda: asyncio.wait_for(
                    operation(),
                    timeout=self.timeout_seconds,
                ),
            )

            elapsed = (
                time.perf_counter()
                - started_at
            )

            return SourceResult(
                source_name=source_name,
                sources=result,
                success=True,
                elapsed_seconds=elapsed,
            )

        except asyncio.TimeoutError:

            elapsed = ( 
                time.perf_counter()
                - started_at
            )

            return SourceResult(
                source_name=source_name,
                sources=[],
                success=False,
                elapsed_seconds=elapsed,
                error=f"{source_name} timeout",
            )

        except Exception as exc:

            elapsed = (
                time.perf_counter()
                - started_at
            )

            return SourceResult(
                source_name=source_name,
                sources=[],
                success=False,
                elapsed_seconds=elapsed,
                error=str(exc),
            )

    async def fetch_sources_parallel(
        self,
        query: str,
    ):
        import httpx

        async with httpx.AsyncClient(timeout=self.timeout_seconds) as client:
            tasks = [
                self.run_source(
                    "wikipedia",
                    lambda: fetch_wikipedia(query, client=client),
                ),
                self.run_source(
                    "arxiv",
                    lambda: fetch_arxiv(query, client=client),
                ),
                self.run_source(
                    "web",
                    lambda: fetch_web(query, client=client),
                ),
            ]

            results = await asyncio.gather(
                *tasks,
                return_exceptions=True,
            )

        collected_sources = []

        for result in results:

            if isinstance(
                result,
                Exception,
            ):
                continue

            if result.success:
                collected_sources.extend(
                    result.sources
                )

            else:
                print(
                    f"ERROR: {result.error}"
                )

        return collected_sources
