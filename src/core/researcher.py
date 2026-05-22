from __future__ import annotations

import logging
from dataclasses import dataclass

from src.config import Settings, configure_environment
from src.services.research_service import ResearchResult, ResearchService
from src.storage.database import db
from src.storage.repository import PostgresRepository
from src.storage.source_cache import build_source_cache

logger = logging.getLogger(__name__)


def configure_logging(level: str) -> None:
    logging.basicConfig(
        level=getattr(logging, level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s - %(message)s",
    )


@dataclass(slots=True)
class Researcher:
    service: ResearchService
    settings: Settings
    _db_connected: bool = False

    async def ask(
        self,
        question: str,
        *,
        source_names: list[str] | None = None,
        no_cache: bool = False,
    ) -> ResearchResult:
        return await self.service.ask(
            question,
            source_names=source_names,
            use_cache=not no_cache,
        )

    async def close(self) -> None:
        if self._db_connected:
            await db.disconnect()


async def create_researcher() -> Researcher:
    settings = configure_environment()
    configure_logging(settings.log_level)

    repository: PostgresRepository | None = None
    db_connected = False

    if settings.database_url:
        try:
            pool = await db.connect(settings.database_url)
            if pool is not None:
                ttl_hours = settings.cache_ttl_seconds / 3600
                repository = PostgresRepository(
                    pool=pool,
                    ttl_hours=ttl_hours,
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
    return Researcher(service=service, settings=settings, _db_connected=db_connected)
