from __future__ import annotations

import json
import asyncio
import logging
import time
from pathlib import Path
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Literal

import httpx

from ai import AnswerWithCitations, Source, fetch_arxiv, fetch_web, fetch_wikipedia, synthesize
from ai.providers.base import ProviderError
from src.config import Settings
from src.services.external_policy import ExternalCallPolicy
from src.storage.repository import PostgresRepository

logger = logging.getLogger(__name__)
# text_log_path = Path(__file__).resolve().parents[2] / "research_service.log"
raw_answer = logging.getLogger("raw_answer_questions")
raw_answer.setLevel(logging.INFO)
raw_answer.propagate = False
file_handler = logging.FileHandler(Path(__file__).resolve().parents[2] / "raw_answer_questions.log", encoding="utf-8")
file_handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s - %(message)s"))
raw_answer.addHandler(file_handler)
SourceName = Literal["wiki", "wikipedia", "arxiv", "web"]

_SOURCE_ALIASES: dict[str, str] = {
    "wiki": "wikipedia",
    "wikipedia": "wikipedia",
    "arxiv": "arxiv",
    "web": "web",
}


@dataclass(frozen=True, slots=True)
class SourceFetchResult:
    """Result of one source fetch attempt."""

    source_type: str
    sources: list[Source]
    from_cache: bool = False
    error: str | None = None
    elapsed_seconds: float = 0.0


@dataclass(frozen=True, slots=True)
class ResearchResult:
    """Full result returned by the research service."""

    question: str
    answer: AnswerWithCitations
    fetch_results: list[SourceFetchResult] = field(default_factory=list)
    degraded: bool = False

    @property
    def all_sources(self) -> list[Source]:
        sources: list[Source] = []
        for result in self.fetch_results:
            sources.extend(result.sources)
        return sources

    @property
    def errors(self) -> list[str]:
        return [
            f"{result.source_type}: {result.error}"
            for result in self.fetch_results
            if result.error
        ]


class ResearchService:
    """
    Business/service layer for Topic 4.

    Responsibilities:
    - validate user question
    - query selected sources concurrently
    - use repository cache when available
    - retry transient source failures
    - degrade gracefully if one source fails
    - call the provided AI synthesizer
    - save final answer to history when repository is configured
    """

    def __init__(
            self,
            settings: Settings,
            *,
            repository: PostgresRepository | None = None,
            max_question_chars: int = 1_000,
            max_retries: int = 3,
            external_policy: ExternalCallPolicy | None = None,
    ) -> None:
        self.settings = settings
        self.repository = repository
        self.max_question_chars = max_question_chars
        self.max_retries = max_retries
        self.external_policy = external_policy or ExternalCallPolicy.from_settings(
            settings,
            max_retries=max_retries,
        )

    async def ask(
            self,
            question: str,
            *,
            source_names: list[str] | None = None,
            use_cache: bool = True,
    ) -> ResearchResult:
        """
        Answer a research question using selected sources.

        Args:
            question: User research question.
            source_names: Optional list like ["wiki", "arxiv"] or ["web"].
                If omitted, all sources are used.
            use_cache: If False, bypasses cache reads but still saves fresh results.

        Returns:
            ResearchResult with final answer, citations, source fetch metadata.

        Raises:
            ValueError: If question or source list is invalid, or no sources are retrieved.
            ProviderError: If synthesis fails.
        """
        clean_question = self._validate_question(question)
        selected_sources = self._normalize_sources(source_names)

        logger.info(
            "Starting research request sources=%s cache=%s",
            selected_sources,
            use_cache,
        )

        fetch_results = await self.fetch_sources(
            clean_question,
            source_names=selected_sources,
            use_cache=use_cache,
        )

        all_sources: list[Source] = []
        for result in fetch_results:
            all_sources.extend(result.sources)

        if not all_sources:
            errors = "; ".join(
                result.error or "no results"
                for result in fetch_results
            )
            raise ValueError(f"No sources were retrieved. Details: {errors}")

        degraded = any(result.error for result in fetch_results)

        logger.info(
            "Fetched %d total sources degraded=%s",
            len(all_sources),
            degraded,
        )
        raw_answer.info(f"question: {clean_question}, sources: {all_sources}")
        # try:
        #     log_path = Path(__file__).resolve().parents[2] / "research_service.log"
        #     with log_path.open("a", encoding="utf-8") as log_file:
        #         log_file.write(
        #             f"{time.strftime('%Y-%m-%d %H:%M:%S')} "
        #             f"Raw sources(before synthesize): {all_sources!r}\n"
        #         )
        # except OSError as exc:
        #     logger.warning("Failed to write raw sources log file: %s", exc)
        try:
            answer = await self.external_policy.call_sync(
                "llm",
                lambda: synthesize(clean_question, all_sources),
            )
        except ProviderError:
            logger.exception("Synthesis provider failed")

            raise
        except ValueError:
            logger.exception("Synthesis input validation failed")
            raise

        if degraded:
            missing = ", ".join(
                result.source_type
                for result in fetch_results
                if result.error
            )
            answer.answer = (
                f"{answer.answer}\n\n"
                f"Note: the result is partially degraded because these sources failed: "
                f"{missing}."
            )

        if self.repository is not None:
            try:
                await self.repository.save_final_answer(clean_question, answer)
            except Exception as exc:
                logger.warning("Failed to save final answer history: %s", exc)

        return ResearchResult(
            question=clean_question,
            answer=answer,
            fetch_results=fetch_results,
            degraded=degraded,
        )

    async def fetch_sources(
            self,
            question: str,
            *,
            source_names: list[str],
            use_cache: bool = True,
    ) -> list[SourceFetchResult]:
        """Fetch all selected sources concurrently with graceful degradation."""
        timeout = self.settings.per_source_timeout_seconds
        async with httpx.AsyncClient(timeout=timeout) as client:
            tasks = [
                self._fetch_one_source(
                    source_type=source_type,
                    question=question,
                    use_cache=use_cache,
                    client=client,
                )
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

    async def _fetch_one_source(
            self,
            *,
            source_type: str,
            question: str,
            use_cache: bool,
            client: httpx.AsyncClient,
    ) -> SourceFetchResult:
        start = time.perf_counter()

        if use_cache and self.repository is not None:
            cached = await self._get_cached_sources(source_type, question)
            if cached is not None:
                return SourceFetchResult(
                    source_type=source_type,
                    sources=cached,
                    from_cache=True,
                    elapsed_seconds=time.perf_counter() - start,
                )

        fetcher = self._get_fetcher(source_type)

        try:
            sources = await self.external_policy.call_async(
                source_type,
                lambda: self._fetch_with_timeout(fetcher, question, client),
            )
        except Exception as exc:
            logger.warning(
                "Source fetch failed source=%s question=%r error=%s",
                source_type,
                question,
                exc,
            )
            return SourceFetchResult(
                source_type=source_type,
                sources=[],
                error=str(exc),
                elapsed_seconds=time.perf_counter() - start,
            )

        if self.repository is not None:
            try:
                await self.repository.save_source_cache(source_type, question, sources)
            except Exception as exc:
                logger.warning(
                    "Failed to save source cache source=%s error=%s",
                    source_type,
                    exc,
                )

        elapsed = time.perf_counter() - start
        logger.info(
            "Fetched source=%s count=%d elapsed=%.3fs",
            source_type,
            len(sources),
            elapsed,
        )

        return SourceFetchResult(
            source_type=source_type,
            sources=sources,
            elapsed_seconds=elapsed,
        )

    async def _fetch_with_timeout(
            self,
            fetcher: Callable[..., Awaitable[list[Source]]],
            question: str,
            client: httpx.AsyncClient,
    ) -> list[Source]:
        timeout = self.settings.per_source_timeout_seconds

        async with asyncio.timeout(timeout):
            return await fetcher(
                question,
                max_results=self.settings.max_sources_per_query,
                client=client,
            )

    async def _get_cached_sources(
            self,
            source_type: str,
            question: str,
    ) -> list[Source] | None:
        if self.repository is None:
            return None

        try:
            cached = await self.repository.get_cached_sources(source_type, question)
        except Exception as exc:
            logger.warning(
                "Cache lookup failed source=%s error=%s",
                source_type,
                exc,
            )
            return None

        if cached is not None:
            logger.info("Cache hit source=%s", source_type)

        return cached

    def _get_fetcher(
            self,
            source_type: str,
    ) -> Callable[..., Awaitable[list[Source]]]:
        if source_type == "wikipedia":
            return fetch_wikipedia
        if source_type == "arxiv":
            return fetch_arxiv
        if source_type == "web":
            return fetch_web

        raise ValueError(f"Unsupported source type: {source_type!r}")

    def _validate_question(self, question: str) -> str:
        clean = question.strip()

        if not clean:
            raise ValueError("Question must be non-empty.")

        if len(clean) > self.max_question_chars:
            raise ValueError(
                f"Question is too long. Maximum length is "
                f"{self.max_question_chars} characters."
            )

        return clean

    def _normalize_sources(self, source_names: list[str] | None) -> list[str]:
        if source_names is None:
            return ["wikipedia", "arxiv", "web"]

        normalized: list[str] = []
        for source in source_names:
            clean = source.strip().lower()
            canonical = _SOURCE_ALIASES.get(clean)
            if canonical is None:
                allowed = ", ".join(sorted(_SOURCE_ALIASES))
                raise ValueError(
                    f"Unsupported source {source!r}. Allowed values: {allowed}."
                )
            if canonical not in normalized:
                normalized.append(canonical)

        if not normalized:
            raise ValueError("At least one source must be selected.")

        return normalized
