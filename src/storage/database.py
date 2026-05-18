"""
Database connection and initialization for research assistant.

This module handles:
- Creating and managing the asyncpg connection pool
"""

import logging
from typing import Optional

import asyncpg
from asyncpg import Pool

logger = logging.getLogger(__name__)


class Database:
    """Manages PostgreSQL connection pool."""

    def __init__(self):
        """Initialize the Database instance."""
        self.pool: Optional[asyncpg.Pool] = None

    async def connect(self, dsn: str) -> Pool | None:
        """
        Create the asyncpg connection pool.
        Args:
            dsn: Database connection string
                 Example: "postgresql://user:password@localhost/dbname"

        Returns:
            The initialized asyncpg.Pool
        """
        self.pool = await asyncpg.create_pool(dsn, min_size=5, max_size=10)
        logger.info("Connected to PostgreSQL")
        return self.pool

    async def disconnect(self) -> None:
        """Close all connections in the pool."""
        if self.pool:
            await self.pool.close()
            logger.info("Disconnected from PostgreSQL")


# Global instance — use this throughout the app for database access
db = Database()