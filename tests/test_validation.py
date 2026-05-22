"""Tests for src.validation input checks and output sanitization."""

from __future__ import annotations

import pytest
from click.testing import CliRunner

from ai.schemas import AnswerWithCitations, Citation, Source
from src.cli import ask
from src.services.research_service import ResearchService
from src.validation import (
    ValidationError,
    sanitize_answer,
    sanitize_fetched_sources,
    sanitize_text,
    validate_question,
    validate_source_names,
)


def _settings_dict(tmp_path):
    from src.config import Settings

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


class TestQuestionValidation:
    def test_rejects_empty(self):
        with pytest.raises(ValidationError, match="non-empty"):
            validate_question("   ")

    def test_rejects_too_short(self):
        with pytest.raises(ValidationError, match="too short"):
            validate_question("ab")

    def test_rejects_punctuation_only(self):
        with pytest.raises(ValidationError, match="letter or digit"):
            validate_question("???")

    def test_rejects_control_characters(self):
        with pytest.raises(ValidationError, match="control"):
            validate_question("What is AI?\x00")

    def test_accepts_normal_question(self):
        assert validate_question("  What is AI?  ") == "What is AI?"


class TestSourceValidation:
    def test_normalizes_wiki_alias(self):
        assert validate_source_names(["wiki", "arxiv"]) == ["wikipedia", "arxiv"]

    def test_rejects_unknown_source(self):
        with pytest.raises(ValidationError, match="Unsupported"):
            validate_source_names(["bad"])


class TestSourceSanitization:
    def test_drops_javascript_url(self):
        bad = Source(
            title="Bad",
            url="javascript:alert(1)",
            snippet="text",
            origin="web",
        )
        good = Source(
            title="Good",
            url="https://example.org",
            snippet="text",
            origin="web",
        )
        result = sanitize_fetched_sources([bad, good])
        assert len(result) == 1
        assert result[0].title == "Good"

    def test_truncates_long_snippet(self):
        src = Source(
            title="T",
            url="https://example.org",
            snippet="x" * 10_000,
            origin="web",
        )
        result = sanitize_fetched_sources([src])
        assert len(result[0].snippet) <= 8000


class TestAnswerSanitization:
    def test_strips_control_chars_from_answer(self):
        raw = AnswerWithCitations(
            question="Q",
            answer="Hello\x07world [1]",
            citations=[],
        )
        clean = sanitize_answer(raw)
        assert "\x07" not in clean.answer
        assert "Helloworld" in clean.answer or "Hello" in clean.answer

    def test_rejects_empty_answer_after_sanitization(self):
        raw = AnswerWithCitations(question="Q", answer="   \x00  ", citations=[])
        with pytest.raises(ValidationError, match="empty"):
            sanitize_answer(raw)

    def test_drops_citation_with_invalid_url(self):
        src = Source(
            title="T",
            url="ftp://files.example/x",
            snippet="s",
            origin="web",
        )
        raw = AnswerWithCitations(
            question="Q",
            answer="See [1]",
            citations=[Citation(index=1, source=src)],
        )
        clean = sanitize_answer(raw)
        assert clean.citations == []


class TestSanitizeText:
    def test_truncates_with_ellipsis(self):
        assert sanitize_text("abcdef", max_length=4) == "abc…"


class TestCliUsesValidation:
    def test_question_too_short_rejected(self):
        runner = CliRunner()
        result = runner.invoke(ask, ["??"])
        assert result.exit_code != 0
        assert "short" in result.output.lower() or "letter" in result.output.lower()


@pytest.mark.asyncio
async def test_service_rejects_all_sources_after_sanitization(tmp_path):
    from unittest.mock import AsyncMock, patch

    from src.concurrency.orchestrator import SourceFetchResult

    settings = _settings_dict(tmp_path)
    bad = Source(
        title="T",
        url="javascript:evil",
        snippet="s",
        origin="web",
    )
    orchestrator = AsyncMock()
    orchestrator.fetch_sources = AsyncMock(
        return_value=[SourceFetchResult(source_type="web", sources=[bad])]
    )
    service = ResearchService(settings=settings, orchestrator=orchestrator)

    with pytest.raises(ValueError, match="No sources were retrieved"):
        with patch("src.services.research_service.synthesize"):
            await service.ask("What is AI?", source_names=["web"])
