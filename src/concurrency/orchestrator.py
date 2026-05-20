import asyncio
import time
from typing import Awaitable

from ai.schemas import Source
from ai.sources import (
    fetch_arxiv,
    fetch_web,
    fetch_wikipedia,
)


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
    ):

        self.timeout_seconds = timeout_seconds

    async def run_source(
        self,
        source_name: str,
        coroutine: Awaitable[list[Source]],
    ) -> SourceResult:

        started_at = time.perf_counter()

        try:

            result = await asyncio.wait_for(
                coroutine,
                timeout=self.timeout_seconds,
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

        tasks = [

            self.run_source(
                "wikipedia",
                fetch_wikipedia(query),
            ),

            self.run_source(
                "arxiv",
                fetch_arxiv(query),
            ),

            self.run_source(
                "web",
                fetch_web(query),
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