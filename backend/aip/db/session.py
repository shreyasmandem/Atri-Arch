"""Async database session management.

SQLite by default so the platform runs with nothing installed; point
`DATABASE_URL` at Postgres for a real deployment and nothing else changes.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from aip.core.config import get_settings
from aip.core.logging import get_logger, log_event
from aip.db.models import Base

logger = get_logger("aip.db")

_engine = None
_factory: async_sessionmaker[AsyncSession] | None = None


def get_engine():
    global _engine
    if _engine is None:
        settings = get_settings()
        url = settings.resolved_database_url
        kwargs: dict = {"echo": False, "future": True}
        if url.startswith("sqlite"):
            # SQLite needs a shared connection for in-memory use and tolerant
            # threading for the async driver.
            kwargs["connect_args"] = {"check_same_thread": False}
            if ":memory:" in url:
                kwargs["poolclass"] = StaticPool
        _engine = create_async_engine(url, **kwargs)
        log_event(logger, "db.engine_created", url=url.split("://")[0])
    return _engine


def get_factory() -> async_sessionmaker[AsyncSession]:
    global _factory
    if _factory is None:
        _factory = async_sessionmaker(
            get_engine(), class_=AsyncSession, expire_on_commit=False
        )
    return _factory


async def init_database() -> None:
    """Create tables. Idempotent, so it is safe on every boot."""
    engine = get_engine()
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    log_event(logger, "db.initialised", tables=len(Base.metadata.tables))


async def dispose_database() -> None:
    global _engine, _factory
    if _engine is not None:
        await _engine.dispose()
    _engine = None
    _factory = None


async def get_session() -> AsyncIterator[AsyncSession]:
    """FastAPI dependency."""
    async with get_factory()() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


@asynccontextmanager
async def session_scope() -> AsyncIterator[AsyncSession]:
    """Context manager for use outside a request."""
    async with get_factory()() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
