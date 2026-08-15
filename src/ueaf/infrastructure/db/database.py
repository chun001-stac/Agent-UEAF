"""Async database engine/session management.

A ``Database`` owns an async engine and an async session factory. Authoritative
operations run inside ``async_session_context()`` which binds a single
``AsyncSession`` to a context-local slot, so the run repository and the outbox
store participate in the same transaction (CON-013): commit on success,
rollback on failure.

The runtime uses the same ``asyncpg`` driver as the migration harness
(``migrations/env.py``), keeping a single PostgreSQL driver across the stack.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from contextvars import ContextVar
from typing import Any

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from ueaf.infrastructure.db.orm import Base

_current_session: ContextVar[AsyncSession | None] = ContextVar(
    "ueaf_current_session", default=None
)


class Database:
    """SQLAlchemy async engine + session context for authoritative persistence."""

    def __init__(
        self,
        url: str,
        *,
        echo: bool = False,
        connect_args: dict[str, Any] | None = None,
        poolclass: Any = None,
    ) -> None:
        self.url = url
        kwargs: dict[str, Any] = {"echo": echo}
        if connect_args is not None:
            kwargs["connect_args"] = connect_args
        if poolclass is not None:
            kwargs["poolclass"] = poolclass
        self._engine: AsyncEngine = create_async_engine(url, **kwargs)
        self._session_factory = async_sessionmaker(
            self._engine, expire_on_commit=False
        )

    @property
    def engine(self) -> AsyncEngine:
        return self._engine

    async def session(self) -> AsyncSession:
        session = _current_session.get()
        if session is None:
            raise RuntimeError(
                "no active database session; use Database.async_session_context()"
            )
        return session

    @asynccontextmanager
    async def async_session_context(self) -> AsyncIterator[AsyncSession]:
        """Bind one AsyncSession for the duration of an authoritative operation."""
        session = self._session_factory()
        token = _current_session.set(session)
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            _current_session.reset(token)
            await session.close()

    async def create_all(self) -> None:
        """Create all tables from ORM metadata (tests / local bootstrap)."""
        async with self._engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)

    async def dispose(self) -> None:
        await self._engine.dispose()


async def memory_database() -> Database:
    """SQLite in-memory async database sharing one connection (unit tests)."""
    from sqlalchemy.pool import StaticPool

    database = Database(
        "sqlite+aiosqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    await database.create_all()
    return database


__all__ = ["Database", "memory_database"]

