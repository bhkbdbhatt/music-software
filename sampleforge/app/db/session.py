"""Async database engine and session factory.

One engine per process, created lazily. Workers and the API run in separate
processes, so nothing is shared between them — each gets its own pool from the
same DSN.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Annotated

from fastapi import Depends
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.core.config import settings

_engine: AsyncEngine | None = None
_session_factory: async_sessionmaker[AsyncSession] | None = None


def get_engine() -> AsyncEngine:
    """Return the process-wide async engine, creating it on first use.

    SQLite is configured with ``check_same_thread=False`` because SQLAlchemy
    hands connections between the event loop thread and the worker threads that
    run our blocking CPU stages.
    """
    global _engine
    if _engine is None:
        url = settings.database_url
        if url.startswith("sqlite"):
            _engine = create_async_engine(url, connect_args={"check_same_thread": False})
        else:
            _engine = create_async_engine(
                url,
                pool_size=settings.db_pool_size,
                max_overflow=settings.db_max_overflow,
                pool_pre_ping=True,
            )
    return _engine


def get_session_factory() -> async_sessionmaker[AsyncSession]:
    """Return the process-wide session factory."""
    global _session_factory
    if _session_factory is None:
        _session_factory = async_sessionmaker(
            bind=get_engine(), expire_on_commit=False, class_=AsyncSession
        )
    return _session_factory


async def get_session() -> AsyncIterator[AsyncSession]:
    """Async context manager yielding a session, committed on clean exit.

    Used as a FastAPI dependency in the API layer. Worker tasks open their own
    sessions per unit of work, since a single job spans several transactions.

    Yields:
        An open :class:`AsyncSession`.
    """
    factory = get_session_factory()
    async with factory() as session:
        try:
            yield session
        except Exception:
            await session.rollback()
            raise


async def create_all() -> None:
    """Create every table declared on :class:`~app.models.db.Base`.

    Development and test convenience only — production uses the Alembic
    migrations in ``alembic/``.
    """
    from app.models.db import Base

    engine = get_engine()
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)


async def dispose_engine() -> None:
    """Close the engine's connections and drop the cached instances."""
    global _engine, _session_factory
    if _engine is not None:
        await _engine.dispose()
    _engine = None
    _session_factory = None


#: Route-dependency form of :func:`get_session`. ``Annotated`` rather than a
#: default argument: the default-argument form evaluates ``Depends(...)`` at
#: import time, which linters rightly flag, and this is the modern FastAPI idiom.
SessionDep = Annotated[AsyncSession, Depends(get_session)]
