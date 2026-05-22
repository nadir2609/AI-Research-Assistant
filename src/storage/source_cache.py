from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path

from ai.schemas import Source
from src.storage.repository import PostgresRepository

logger = logging.getLogger(__name__)

_ALLOWED_SOURCES = {"wikipedia", "arxiv", "web"}


def _normalize_query(query: str) -> str:
    return " ".join((query or "").strip().lower().split())


def _validate_source_type(source_type: str) -> None:
    if source_type not in _ALLOWED_SOURCES:
        raise ValueError(f"Unsupported source_type: {source_type}")


class SourceCache(ABC):
    @abstractmethod
    async def get(self, source_type: str, query: str) -> list[Source] | None:
        raise NotImplementedError

    @abstractmethod
    async def set(self, source_type: str, query: str, sources: list[Source]) -> None:
        raise NotImplementedError


@dataclass(slots=True)
class FileSourceCache(SourceCache):
    cache_dir: Path
    ttl_seconds: int

    def __post_init__(self) -> None:
        if self.ttl_seconds < 1:
            raise ValueError("ttl_seconds must be >= 1.")
        self.cache_dir.mkdir(parents=True, exist_ok=True)

    async def get(self, source_type: str, query: str) -> list[Source] | None:
        return await asyncio.to_thread(self._get_sync, source_type, query)

    async def set(self, source_type: str, query: str, sources: list[Source]) -> None:
        await asyncio.to_thread(self._set_sync, source_type, query, sources)

    def _get_sync(self, source_type: str, query: str) -> list[Source] | None:
        _validate_source_type(source_type)
        normalized = _normalize_query(query)
        if not normalized:
            return None
        path = self._path_for(source_type, normalized)
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return None
        except (OSError, json.JSONDecodeError, ValueError, TypeError) as exc:
            logger.warning("Cache read failed for %s: %s", path, exc)
            return None

        created_at = payload.get("created_at")
        if not isinstance(created_at, (int, float)):
            return None
        if time.time() - created_at > self.ttl_seconds:
            return None

        items = payload.get("sources")
        if not isinstance(items, list):
            return None

        try:
            return [Source(**item) for item in items]
        except (ValueError, TypeError) as exc:
            logger.warning("Cache payload invalid for %s: %s", path, exc)
            return None

    def _set_sync(self, source_type: str, query: str, sources: list[Source]) -> None:
        _validate_source_type(source_type)
        normalized = _normalize_query(query)
        if not normalized:
            raise ValueError("query must be non-empty")
        payload = {
            "source_type": source_type,
            "query": normalized,
            "created_at": time.time(),
            "sources": [source.model_dump() for source in sources],
        }
        path = self._path_for(source_type, normalized)
        tmp_path = path.with_suffix(".tmp")
        tmp_path.write_text(json.dumps(payload), encoding="utf-8")
        tmp_path.replace(path)

    def _path_for(self, source_type: str, query: str) -> Path:
        digest = hashlib.sha256(query.encode("utf-8")).hexdigest()
        filename = f"{source_type}-{digest}.json"
        return self.cache_dir / filename


class CompositeSourceCache(SourceCache):
    def __init__(
        self,
        *,
        file_cache: FileSourceCache | None,
        repository: PostgresRepository | None,
    ) -> None:
        self._file_cache = file_cache
        self._repository = repository

    async def get(self, source_type: str, query: str) -> list[Source] | None:
        if self._repository is not None:
            try:
                cached = await self._repository.get_cached_sources(source_type, query)
            except Exception as exc:
                logger.warning("Repository cache lookup failed: %s", exc)
                cached = None
            if cached is not None:
                return cached

        if self._file_cache is None:
            return None
        return await self._file_cache.get(source_type, query)

    async def set(self, source_type: str, query: str, sources: list[Source]) -> None:
        successes = 0
        errors: list[Exception] = []

        if self._repository is not None:
            try:
                await self._repository.save_source_cache(source_type, query, sources)
                successes += 1
            except Exception as exc:
                errors.append(exc)
                logger.warning("Repository cache write failed: %s", exc)

        if self._file_cache is not None:
            try:
                await self._file_cache.set(source_type, query, sources)
                successes += 1
            except Exception as exc:
                errors.append(exc)
                logger.warning("File cache write failed: %s", exc)

        if successes == 0 and errors:
            raise errors[0]


def build_source_cache(
    *,
    cache_dir: Path | str | None,
    ttl_seconds: int,
    repository: PostgresRepository | None = None,
) -> SourceCache | None:
    file_cache = None
    if cache_dir is not None and ttl_seconds > 0:
        file_cache = FileSourceCache(cache_dir=Path(cache_dir), ttl_seconds=ttl_seconds)

    if repository is None:
        return file_cache
    return CompositeSourceCache(file_cache=file_cache, repository=repository)
