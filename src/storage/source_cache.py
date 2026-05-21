"""Source-result caching keyed by (source_type, query) with configurable TTL."""

from __future__ import annotations

import asyncio
import json
import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from ai.schemas import Source
from src.storage.cache_keys import cache_file_stem, canonicalize_query, validate_source_type
from src.storage.repository import PostgresRepository

logger = logging.getLogger(__name__)


class SourceCache(ABC):
    """Async cache for ``list[Source]`` results per (source_type, query)."""

    @abstractmethod
    async def get(self, source_type: str, query: str) -> list[Source] | None:
        """Return cached sources if present and not expired."""

    @abstractmethod
    async def set(self, source_type: str, query: str, sources: list[Source]) -> None:
        """Persist sources for later lookups."""


@dataclass(frozen=True, slots=True)
class _FilesystemEntry:
    source_type: str
    query: str
    created_at: datetime
    sources: list[Source]

    def to_dict(self) -> dict[str, Any]:
        return {
            "source_type": self.source_type,
            "query": self.query,
            "created_at": self.created_at.isoformat(),
            "sources": [source.model_dump() for source in self.sources],
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> _FilesystemEntry:
        created_raw = payload["created_at"]
        if isinstance(created_raw, str):
            created_at = datetime.fromisoformat(created_raw)
            if created_at.tzinfo is None:
                created_at = created_at.replace(tzinfo=timezone.utc)
        else:
            raise ValueError("created_at must be an ISO-8601 string")

        sources = [Source(**item) for item in payload["sources"]]
        return cls(
            source_type=str(payload["source_type"]),
            query=str(payload["query"]),
            created_at=created_at,
            sources=sources,
        )


class FilesystemSourceCache(SourceCache):
    """JSON file cache under ``CACHE_DIR/sources/<source_type>/<stem>.json``."""

    def __init__(self, cache_dir: Path, *, ttl_seconds: int) -> None:
        if ttl_seconds < 1:
            raise ValueError("ttl_seconds must be >= 1")
        self._root = Path(cache_dir).expanduser().resolve() / "sources"
        self._ttl = timedelta(seconds=ttl_seconds)
        self._root.mkdir(parents=True, exist_ok=True)

    def _path_for(self, source_type: str, query: str) -> Path:
        stem = cache_file_stem(source_type, query)
        return self._root / source_type / f"{stem}.json"

    async def get(self, source_type: str, query: str) -> list[Source] | None:
        validate_source_type(source_type)
        path = self._path_for(source_type, query)

        def _read() -> list[Source] | None:
            if not path.is_file():
                return None
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
                entry = _FilesystemEntry.from_dict(payload)
            except (OSError, json.JSONDecodeError, ValueError, TypeError) as exc:
                logger.warning("Invalid cache file %s: %s", path, exc)
                return None

            age = datetime.now(timezone.utc) - entry.created_at
            if age >= self._ttl:
                logger.info("Filesystem cache expired %s", path.name)
                try:
                    path.unlink(missing_ok=True)
                except OSError:
                    pass
                return None

            logger.info(
                "Filesystem cache hit source=%s query=%r",
                source_type,
                entry.query,
            )
            return entry.sources

        return await asyncio.to_thread(_read)

    async def set(self, source_type: str, query: str, sources: list[Source]) -> None:
        validate_source_type(source_type)
        canonical = canonicalize_query(query)
        if not canonical:
            raise ValueError("query must be non-empty")

        entry = _FilesystemEntry(
            source_type=source_type,
            query=canonical,
            created_at=datetime.now(timezone.utc),
            sources=sources,
        )
        path = self._path_for(source_type, query)

        def _write() -> None:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(
                json.dumps(entry.to_dict(), indent=2),
                encoding="utf-8",
            )

        await asyncio.to_thread(_write)
        logger.debug("Filesystem cache saved %s", path)


class PostgresSourceCache(SourceCache):
    """Adapter around :class:`PostgresRepository` for source-result caching."""

    def __init__(self, repository: PostgresRepository) -> None:
        self._repository = repository

    async def get(self, source_type: str, query: str) -> list[Source] | None:
        return await self._repository.get_cached_sources(source_type, query)

    async def set(self, source_type: str, query: str, sources: list[Source]) -> None:
        await self._repository.save_source_cache(source_type, query, sources)


class TieredSourceCache(SourceCache):
    """Read through backends in order; write to every backend."""

    def __init__(self, backends: list[SourceCache]) -> None:
        if not backends:
            raise ValueError("At least one cache backend is required.")
        self._backends = backends

    async def get(self, source_type: str, query: str) -> list[Source] | None:
        for backend in self._backends:
            try:
                cached = await backend.get(source_type, query)
            except Exception as exc:
                logger.warning(
                    "Cache lookup failed backend=%s error=%s",
                    type(backend).__name__,
                    exc,
                )
                continue
            if cached is not None:
                return cached
        return None

    async def set(self, source_type: str, query: str, sources: list[Source]) -> None:
        for backend in self._backends:
            try:
                await backend.set(source_type, query, sources)
            except Exception as exc:
                logger.warning(
                    "Cache save failed backend=%s error=%s",
                    type(backend).__name__,
                    exc,
                )


def build_source_cache(
    *,
    cache_dir: Path,
    ttl_seconds: int,
    repository: PostgresRepository | None = None,
) -> SourceCache:
    """Filesystem cache always; PostgreSQL prepended when a repository is available."""
    backends: list[SourceCache] = [
        FilesystemSourceCache(cache_dir, ttl_seconds=ttl_seconds),
    ]
    if repository is not None:
        backends.insert(0, PostgresSourceCache(repository))
    if len(backends) == 1:
        return backends[0]
    return TieredSourceCache(backends)
