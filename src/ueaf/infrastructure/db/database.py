"""异步数据库引擎/会话管理。

``Database`` 拥有一个异步引擎和一个异步会话工厂。权威操作在
``async_session_context()`` 内运行，它将单个 ``AsyncSession`` 绑定到
context-local 槽位，因此运行仓库与 outbox 存储参与同一个事务（CON-013）：
成功则提交，失败则回滚。

运行时使用与迁移脚手架（``migrations/env.py``）相同的 ``asyncpg`` 驱动，
使整个技术栈保持单一的 PostgreSQL 驱动。
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
    """用于权威持久化的 SQLAlchemy 异步引擎 + 会话上下文。"""

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
        """在权威操作期间绑定一个 AsyncSession。"""
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
        """根据 ORM metadata 创建所有表（测试 / 本地引导）。"""
        async with self._engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)

    async def dispose(self) -> None:
        await self._engine.dispose()


async def memory_database() -> Database:
    """共享单一连接的 SQLite 内存异步数据库（单元测试）。"""
    from sqlalchemy.pool import StaticPool

    database = Database(
        "sqlite+aiosqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    await database.create_all()
    return database


__all__ = ["Database", "memory_database"]

