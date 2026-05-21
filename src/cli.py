from __future__ import annotations

import asyncio
import logging
from typing import NoReturn

import click

from ai.providers.base import ProviderError

from src.config import SettingsError, configure_environment
from src.services.external_policy import is_quota_exhausted
from src.services.research_service import ResearchResult, ResearchService
from src.storage.database import db
from src.storage.repository import PostgresRepository
from src.storage.source_cache import build_source_cache
from src.validation import (
    MAX_QUESTION_CHARS,
    ValidationError,
    sanitize_text,
    validate_question,
    validate_source_names,
)

logger = logging.getLogger(__name__)


def _configure_logging(level: str) -> None:
    logging.basicConfig(
        level=getattr(logging, level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s - %(message)s",
    )


def _parse_sources_option(value: str | None) -> list[str] | None:
    """Split comma-separated --sources into raw tokens."""
    if value is None:
        return None
    parts = [part.strip() for part in value.split(",") if part.strip()]
    return parts or None


def _render_result(result: ResearchResult) -> str:
    question = sanitize_text(result.answer.question, max_length=MAX_QUESTION_CHARS)
    answer_text = sanitize_text(result.answer.answer, max_length=32_000)

    lines: list[str] = [
        f"Q: {question}",
        "",
        f"A: {answer_text}",
        "",
    ]

    if result.answer.citations:
        lines.append("References:")
        for citation in result.answer.citations:
            source = citation.source
            title = sanitize_text(source.title, max_length=500)
            url = sanitize_text(source.url, max_length=2048)
            lines.append(
                f"  [{citation.index}] ({source.origin}) {title}"
            )
            lines.append(f"      {url}")
    else:
        lines.append("References: none cited by the model.")

    lines.append("")
    lines.append("Source fetch summary:")
    for fetch_result in result.fetch_results:
        status = "cache" if fetch_result.from_cache else "live"
        if fetch_result.error:
            status = f"failed: {fetch_result.error}"

        lines.append(
            f"  - {fetch_result.source_type}: "
            f"{len(fetch_result.sources)} source(s), "
            f"{status}, "
            f"{fetch_result.elapsed_seconds:.2f}s"
        )

    if result.degraded:
        lines.append("")
        lines.append("Warning: answer was produced with partial source failures.")

    return "\n".join(lines)


async def _build_service() -> tuple[ResearchService, bool]:
    settings = configure_environment()
    _configure_logging(settings.log_level)

    repository: PostgresRepository | None = None
    db_connected = False

    if settings.database_url:
        try:
            pool = await db.connect(settings.database_url)
            if pool is not None:
                repository = PostgresRepository(
                    pool=pool,
                    ttl_seconds=settings.cache_ttl_seconds,
                )
                db_connected = True
        except Exception as exc:
            logger.warning(
                "Database unavailable; continuing without PostgreSQL cache: %s",
                exc,
            )

    source_cache = build_source_cache(
        cache_dir=settings.cache_dir,
        ttl_seconds=settings.cache_ttl_seconds,
        repository=repository,
    )

    service = ResearchService(
        settings=settings,
        source_cache=source_cache,
        repository=repository,
        max_retries=settings.external_max_retries,
    )
    return service, db_connected

async def _ask_async(
        question: str,
        *,
        source_names: list[str] | None,
        no_cache: bool,
) -> int:
    service, db_connected = await _build_service()

    try:
        result = await service.ask(
            question,
            source_names=source_names,
            use_cache=not no_cache,
        )
    except (ValidationError, ValueError, SettingsError) as exc:
        click.echo(f"Error: {exc}", err=True)
        return 2
    except ProviderError as exc:
        if is_quota_exhausted(exc):
            click.echo(
                "LLM quota exhausted for the configured provider/model. "
                "Wait for the daily limit to reset, enable billing in Google AI Studio, "
                "switch LLM_MODEL (e.g. gemini-2.0-flash), or set LLM_PROVIDER to "
                "anthropic/openai with a valid API key.",
                err=True,
            )
            return 1
        logger.exception("Research request failed")
        click.echo(f"Research failed: {exc}", err=True)
        return 1
    except Exception as exc:
        logger.exception("Research request failed")
        click.echo(f"Research failed: {exc}", err=True)
        return 1
    finally:
        if db_connected:
            await db.disconnect()

    click.echo(_render_result(result))
    return 0


@click.group(context_settings={"help_option_names": ["-h", "--help"]})
def cli() -> None:
    """Async Research Assistant CLI."""


@cli.command()
@click.argument("question", nargs=-1, required=True)
@click.option(
    "--sources",
    help="Comma-separated source subset: wiki,arxiv,web. Example: --sources wiki,arxiv",
)
@click.option(
    "--no-cache",
    is_flag=True,
    help="Bypass cache reads for this request.",
)
def ask(
        question: tuple[str, ...],
        sources: str | None,
        no_cache: bool,
) -> None:
    """
    Ask a research question.

    Example:

        python -m src.cli ask "What is photosynthesis?" --sources wiki,web
    """
    question_text = " ".join(question).strip()
    try:
        validate_question(question_text, max_chars=MAX_QUESTION_CHARS)
        validated_sources = validate_source_names(_parse_sources_option(sources))
    except ValidationError as exc:
        raise click.BadParameter(str(exc)) from exc

    exit_code = asyncio.run(
        _ask_async(
            question_text,
            source_names=validated_sources,
            no_cache=no_cache,
        )
    )

    if exit_code:
        raise click.exceptions.Exit(exit_code)


def main() -> NoReturn:
    cli()
    raise SystemExit(0)


if __name__ == "__main__":
    main()
