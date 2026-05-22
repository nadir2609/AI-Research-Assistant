"""Input validation and output sanitization for the SE layer.

The provided ``ai/`` package validates its own schemas; this module adds
application-level checks at CLI/service boundaries and cleans data before
display, caching, or persistence.
"""

from __future__ import annotations

import logging
import re
import unicodedata
from typing import Final
from urllib.parse import urlparse

from ai.schemas import AnswerWithCitations, Citation, Source

logger = logging.getLogger(__name__)

# --- Question limits ---
MIN_QUESTION_CHARS: Final[int] = 3
MAX_QUESTION_CHARS: Final[int] = 1_000

# --- Source field limits (SE layer; stricter than raw API payloads) ---
MAX_SOURCE_TITLE_CHARS: Final[int] = 500
MAX_SOURCE_SNIPPET_CHARS: Final[int] = 8_000
MAX_SOURCE_URL_CHARS: Final[int] = 2_048

# --- Answer limits ---
MAX_ANSWER_CHARS: Final[int] = 32_000
MAX_DEGRADED_NOTE_CHARS: Final[int] = 500

_ALLOWED_SOURCE_ALIASES: Final[dict[str, str]] = {
    "wiki": "wikipedia",
    "wikipedia": "wikipedia",
    "arxiv": "arxiv",
    "web": "web",
}

# Remove C0/C1 control chars except tab, LF, CR.
_CONTROL_CHAR_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f\x80-\x9f]")
# Collapse 3+ blank lines to two newlines.
_EXCESS_NEWLINES_RE = re.compile(r"\n{3,}")
# Question must contain at least one letter or digit.
_HAS_ALNUM_RE = re.compile(r"[\w]", re.UNICODE)


class ValidationError(ValueError):
    """Raised when user input fails validation."""


def validate_question(
    question: str,
    *,
    min_chars: int = MIN_QUESTION_CHARS,
    max_chars: int = MAX_QUESTION_CHARS,
) -> str:
    """Validate and normalize a research question.

    Raises:
        ValidationError: Empty, too short/long, non-text, or control characters.
    """
    if question is None:
        raise ValidationError("Question must be a string.")

    cleaned = _strip_and_normalize_whitespace(question)
    if not cleaned:
        raise ValidationError("Question must be non-empty.")

    if len(cleaned) < min_chars:
        raise ValidationError(
            f"Question is too short. Minimum length is {min_chars} characters."
        )

    if len(cleaned) > max_chars:
        raise ValidationError(
            f"Question is too long. Maximum length is {max_chars} characters."
        )

    if not _HAS_ALNUM_RE.search(cleaned):
        raise ValidationError(
            "Question must contain at least one letter or digit."
        )

    if _contains_disallowed_controls(question):
        raise ValidationError("Question contains invalid control characters.")

    return cleaned


def validate_source_names(source_names: list[str] | None) -> list[str]:
    """Parse and validate CLI/service source subset names."""
    if source_names is None:
        return ["wikipedia", "arxiv", "web"]

    normalized: list[str] = []
    for raw in source_names:
        if raw is None:
            continue
        clean = raw.strip().lower()
        if not clean:
            raise ValidationError("Source names must not be empty.")
        canonical = _ALLOWED_SOURCE_ALIASES.get(clean)
        if canonical is None:
            allowed = ", ".join(sorted(_ALLOWED_SOURCE_ALIASES))
            raise ValidationError(
                f"Unsupported source {raw!r}. Allowed values: {allowed}."
            )
        if canonical not in normalized:
            normalized.append(canonical)

    if not normalized:
        raise ValidationError("At least one source must be selected.")

    return normalized


def sanitize_fetched_sources(sources: list[Source]) -> list[Source]:
    """Drop or clean upstream sources before synthesis and caching.

    Invalid entries are logged and skipped so one bad payload does not crash
    the pipeline.
    """
    cleaned: list[Source] = []
    for source in sources:
        try:
            cleaned.append(_sanitize_source(source))
        except ValidationError as exc:
            logger.warning("Dropping invalid source %r: %s", source.title, exc)

    return cleaned


def sanitize_answer(
    answer: AnswerWithCitations,
    *,
    max_answer_chars: int = MAX_ANSWER_CHARS,
) -> AnswerWithCitations:
    """Sanitize LLM output before CLI display, caching, or DB storage."""
    safe_question = sanitize_text(answer.question, max_length=MAX_QUESTION_CHARS)
    safe_answer = sanitize_text(answer.answer, max_length=max_answer_chars)

    if not safe_answer.strip():
        raise ValidationError("Synthesized answer is empty after sanitization.")

    safe_citations: list[Citation] = []
    for citation in answer.citations:
        try:
            safe_source = _sanitize_source(citation.source)
        except ValidationError as exc:
            logger.warning(
                "Dropping citation index=%s: %s",
                citation.index,
                exc,
            )
            continue
        if citation.index < 1:
            logger.warning("Dropping citation with invalid index=%s", citation.index)
            continue
        safe_citations.append(
            Citation(index=citation.index, source=safe_source)
        )

    return AnswerWithCitations(
        question=safe_question,
        answer=safe_answer,
        citations=safe_citations,
    )


def append_degraded_note(answer: AnswerWithCitations, missing_sources: str) -> str:
    """Build a safe degradation footer (returns new answer text)."""
    note = (
        "Note: the result is partially degraded because these sources failed: "
        f"{sanitize_text(missing_sources, max_length=MAX_DEGRADED_NOTE_CHARS)}."
    )
    combined = f"{answer.answer}\n\n{note}"
    return sanitize_text(combined, max_length=MAX_ANSWER_CHARS + MAX_DEGRADED_NOTE_CHARS)


def sanitize_text(text: str, *, max_length: int) -> str:
    """Remove control characters and cap length for safe terminal/display output."""
    if text is None:
        return ""
    normalized = unicodedata.normalize("NFKC", str(text))
    without_controls = _CONTROL_CHAR_RE.sub("", normalized)
    collapsed = _EXCESS_NEWLINES_RE.sub("\n\n", without_controls)
    trimmed = collapsed.strip()
    if len(trimmed) > max_length:
        if max_length <= 1:
            trimmed = "…"[:max_length]
        else:
            trimmed = trimmed[: max_length - 1].rstrip() + "…"
    return trimmed


def _sanitize_source(source: Source) -> Source:
    title = sanitize_text(source.title, max_length=MAX_SOURCE_TITLE_CHARS)
    snippet = sanitize_text(source.snippet, max_length=MAX_SOURCE_SNIPPET_CHARS)
    url = _validate_url(source.url)
    origin = source.origin
    if origin not in ("wikipedia", "arxiv", "web"):
        raise ValidationError(f"Invalid origin: {origin!r}")

    if not title:
        raise ValidationError("Source title is empty after sanitization.")
    if not snippet:
        raise ValidationError("Source snippet is empty after sanitization.")

    return Source(title=title, url=url, snippet=snippet, origin=origin)


def _validate_url(url: str) -> str:
    raw = (url or "").strip()
    if not raw:
        raise ValidationError("Source URL is empty.")
    if len(raw) > MAX_SOURCE_URL_CHARS:
        raise ValidationError("Source URL is too long.")
    if _contains_disallowed_controls(raw):
        raise ValidationError("Source URL contains invalid control characters.")

    parsed = urlparse(raw)
    if parsed.scheme not in ("http", "https"):
        raise ValidationError(
            f"Source URL must use http or https scheme, got {parsed.scheme!r}."
        )
    if not parsed.netloc:
        raise ValidationError("Source URL must include a host.")

    return raw


def _strip_and_normalize_whitespace(text: str) -> str:
    normalized = unicodedata.normalize("NFKC", text)
    without_controls = _CONTROL_CHAR_RE.sub("", normalized)
    return " ".join(without_controls.split())


def _contains_disallowed_controls(text: str) -> bool:
    return bool(_CONTROL_CHAR_RE.search(text))
