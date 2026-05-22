"""Canonical cache keys for (source_type, query) lookups."""

from __future__ import annotations

import hashlib
import re

_ALLOWED_SOURCE_TYPES = frozenset({"wikipedia", "arxiv", "web"})

# Strip trailing sentence punctuation so "photosynthesis?" matches "photosynthesis".
_TRAILING_PUNCT_RE = re.compile(r"[?.!,;:]+$")


def canonicalize_query(query: str) -> str:
    """Normalize a research question for cache lookup and storage.

    "WHAT IS PHOTOSYNTHESIS?" and "what is photosynthesis  " map to the
    same key: "what is photosynthesis".
    """
    collapsed = " ".join(query.strip().lower().split())
    if not collapsed:
        return ""
    return _TRAILING_PUNCT_RE.sub("", collapsed)


def validate_source_type(source_type: str) -> str:
    if source_type not in _ALLOWED_SOURCE_TYPES:
        raise ValueError(f"Unsupported source_type: {source_type}")
    return source_type


def cache_file_stem(source_type: str, query: str) -> str:
    """Stable filename stem for a (source_type, canonical_query) pair."""
    validate_source_type(source_type)
    canonical = canonicalize_query(query)
    if not canonical:
        raise ValueError("query must be non-empty after canonicalization")
    digest = hashlib.sha256(f"{source_type}:{canonical}".encode("utf-8")).hexdigest()[:32]
    return f"{source_type}_{digest}"
