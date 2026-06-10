"""Async SQLAlchemy session factory."""

from __future__ import annotations

import os
from collections.abc import AsyncGenerator

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

_engine: AsyncEngine | None = None
_session_factory: async_sessionmaker[AsyncSession] | None = None


def normalize_database_url(url: str) -> str:
    if not url:
        raise RuntimeError("DATABASE_URL is not set")
    if url.startswith("postgresql+asyncpg://"):
        return url
    if url.startswith("postgresql://"):
        return url.replace("postgresql://", "postgresql+asyncpg://", 1)
    raise ValueError(f"Unsupported DATABASE_URL scheme: {url.split(':', 1)[0]}")


def get_database_url() -> str:
    return normalize_database_url(os.environ.get("DATABASE_URL", ""))


def get_engine() -> AsyncEngine:
    global _engine
    if _engine is None:
        _engine = create_async_engine(get_database_url(), pool_pre_ping=True)
    return _engine


def async_session_factory() -> async_sessionmaker[AsyncSession]:
    global _session_factory
    if _session_factory is None:
        _session_factory = async_sessionmaker(
            get_engine(),
            expire_on_commit=False,
            autoflush=False,
        )
    return _session_factory


async def get_session() -> AsyncGenerator[AsyncSession, None]:
    session = async_session_factory()()
    try:
        yield session
    finally:
        await session.close()


def reset_engine() -> None:
    """Drop cached engine (tests)."""
    global _engine, _session_factory
    _engine = None
    _session_factory = None
