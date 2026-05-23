from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from pathlib import Path

from ai import AnswerWithCitations, Source, synthesize
from ai.providers.base import ProviderError
from src.concurrency.orchestrator import ResearchOrchestrator, SourceFetchResult
from src.config import Settings
from src.services.external_policy import ExternalCallPolicy
from src.storage.repository import PostgresRepository
from src.storage.source_cache import SourceCache
from src.validation import (
    MAX_QUESTION_CHARS,
    ValidationError,
    append_degraded_note,
    sanitize_answer,
    sanitize_fetched_sources,
    validate_question,
    validate_source_names,
)

logger = logging.getLogger(__name__)


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
    - use repository cache when available
    - delegate parallel source fetch to ResearchOrchestrator
    - call the provided AI synthesizer
    - save final answer to history when repository is configured
    """

    def __init__(
        self,
        settings: Settings,
        *,
        source_cache: SourceCache | None = None,
        repository: PostgresRepository | None = None,
        max_question_chars: int = MAX_QUESTION_CHARS,
        max_retries: int = 3,
        external_policy: ExternalCallPolicy | None = None,
        orchestrator: ResearchOrchestrator | None = None,
    ) -> None:
        self.settings = settings
        self.source_cache = source_cache
        self.repository = repository
        self.max_question_chars = max_question_chars
        self.max_retries = max_retries
        self.external_policy = external_policy or ExternalCallPolicy.from_settings(
            settings,
            max_retries=max_retries,
        )
        self._orchestrator = orchestrator or ResearchOrchestrator(
            settings=settings,
            policy=self.external_policy,
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
        clean_question = validate_question(
            question,
            max_chars=self.max_question_chars,
        )
        selected_sources = validate_source_names(source_names)

        logger.info(
            "Starting research request sources=%s cache=%s",
            selected_sources,
            use_cache,
        )

        fetch_results = await self._fetch_sources_with_cache(
            clean_question,
            source_names=selected_sources,
            use_cache=use_cache,
        )

        fetch_results = self._limit_sources_per_origin(fetch_results)

        all_sources: list[Source] = []
        for result in fetch_results:
            all_sources.extend(result.sources)

        all_sources = sanitize_fetched_sources(all_sources)

        if not all_sources:
            errors = "; ".join(result.error or "no results" for result in fetch_results)
            raise ValueError(f"No sources were retrieved. Details: {errors}")

        degraded = any(result.error for result in fetch_results)

        logger.info(
            "Fetched %d total sources degraded=%s",
            len(all_sources),
            degraded,
        )
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

        try:
            answer = sanitize_answer(answer)
        except ValidationError:
            logger.exception("Synthesized answer failed output sanitization")
            raise

        if degraded:
            missing = ", ".join(
                result.source_type for result in fetch_results if result.error
            )
            answer = AnswerWithCitations(
                question=answer.question,
                answer=append_degraded_note(answer, missing),
                citations=answer.citations,
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

    async def _fetch_sources_with_cache(
        self,
        question: str,
        *,
        source_names: list[str],
        use_cache: bool,
    ) -> list[SourceFetchResult]:
        """Resolve cache hits, then fetch remaining sources in parallel."""
        by_name: dict[str, SourceFetchResult] = {}
        misses: list[str] = []

        for source_type in source_names:
            start = time.perf_counter()
            if use_cache and self.source_cache is not None:
                cached = await self._get_cached_sources(source_type, question)
                if cached is not None:
                    by_name[source_type] = SourceFetchResult(
                        source_type=source_type,
                        sources=cached,
                        from_cache=True,
                        elapsed_seconds=time.perf_counter() - start,
                    )
                    continue
            misses.append(source_type)

        if misses:
            live_results = await self._orchestrator.fetch_sources(question, misses)
            for result in live_results:
                if (
                    result.error is None
                    and result.sources
                    and self.source_cache is not None
                ):
                    try:
                        await self.source_cache.set(
                            result.source_type,
                            question,
                            result.sources,
                        )
                    except Exception as exc:
                        logger.warning(
                            "Failed to save source cache source=%s error=%s",
                            result.source_type,
                            exc,
                        )
                by_name[result.source_type] = result

        return [by_name[name] for name in source_names if name in by_name]

    def _limit_sources_per_origin(
        self,
        fetch_results: list[SourceFetchResult],
    ) -> list[SourceFetchResult]:
        limit = self.settings.max_sources_per_query
        if limit < 1:
            return fetch_results

        trimmed: list[SourceFetchResult] = []
        for result in fetch_results:
            sources = result.sources[:limit]
            if len(sources) == len(result.sources):
                trimmed.append(result)
                continue
            trimmed.append(
                SourceFetchResult(
                    source_type=result.source_type,
                    sources=sources,
                    from_cache=result.from_cache,
                    elapsed_seconds=result.elapsed_seconds,
                    error=result.error,
                )
            )
        return trimmed

    async def _get_cached_sources(
        self,
        source_type: str,
        question: str,
    ) -> list[Source] | None:
        if self.source_cache is None:
            return None

        try:
            cached = await self.source_cache.get(source_type, question)
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

