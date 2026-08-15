"""Database engine/session management.

A ``Database`` owns an engine and a session factory. Authoritative operations
run inside ``session_context()`` which binds a single SQLAlchemy ``Session`` to
a context-local slot, so the run repository and the outbox store participate in
the same transaction (CON-013): commit on success, rollback on failure.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from typing import Any

from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from ueaf.infrastructure.db.orm import Base

_current_session: ContextVar[Session | None] = ContextVar(
    "ueaf_current_session", default=None
)


class Database:
    """SQLAlchemy engine + session context for authoritative persistence."""

    def __init__(
        self,
        url: str,
        *,
        echo: bool = False,
        connect_args: dict[str, Any] | None = None,
        poolclass: Any = None,
    ) -> None:
        self.url = url
        kwargs: dict[str, Any] = {"echo": echo, "future": True}
        if connect_args is not None:
            kwargs["connect_args"] = connect_args
        if poolclass is not None:
            kwargs["poolclass"] = poolclass
        self._engine: Engine = create_engine(url, **kwargs)
        self._session_factory = sessionmaker(
            bind=self._engine, expire_on_commit=False, future=True
        )

    @property
    def engine(self) -> Engine:
        return self._engine

    def session(self) -> Session:
        session = _current_session.get()
        if session is None:
            raise RuntimeError(
                "no active database session; use Database.session_context()"
            )
        return session

    @contextmanager
    def session_context(self) -> Iterator[Session]:
        """Bind one Session for the duration of an authoritative operation."""
        session = self._session_factory()
        token = _current_session.set(session)
        try:
            yield session
            session.commit()
        except Exception:
            session.rollback()
            raise
        finally:
            _current_session.reset(token)
            session.close()

    def create_all(self) -> None:
        """Create all tables from ORM metadata (tests / local bootstrap)."""
        Base.metadata.create_all(self._engine)

    def dispose(self) -> None:
        self._engine.dispose()


def memory_database() -> Database:
    """SQLite in-memory database sharing one connection (unit tests)."""
    from sqlalchemy.pool import StaticPool

    database = Database(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    database.create_all()
    return database


__all__ = ["Database", "memory_database", "Any"]
