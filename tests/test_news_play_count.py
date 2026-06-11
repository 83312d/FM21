"""News play_count Redis mirror and midnight reset tests (U19)."""

from __future__ import annotations

import os
from datetime import UTC, datetime, timedelta

import pytest
import redis
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from services.db.migrate import run_migrations
from services.db.models import NewsItem
from services.db.session import async_session_factory, get_engine, reset_engine
from services.news.db.models import NewsFetchInput
from services.news.db.repository import NewsItemRepository
from services.news.play_count import (
    PLAYED_TTL_SEC,
    clear_played_keys,
    get_played_count,
    increment_played_count,
    is_at_play_cap,
    played_key,
)
from services.news.workers.play_count_reset import (
    PlayCountResetWorker,
    reset_postgres_play_counts,
    seconds_until_next_midnight_utc,
)



@pytest.fixture(autouse=True)
def _reset_engine():
    reset_engine()
    yield
    reset_engine()


@pytest.fixture
def redis_client() -> redis.Redis:
    url = os.environ.get("REDIS_URL", "redis://redis:6379/0")
    client = redis.Redis.from_url(url, decode_responses=True)
    client.flushdb()
    yield client
    client.flushdb()


@pytest.fixture
async def migrated_db():
    await run_migrations()
    yield
    engine = get_engine()
    async with engine.begin() as conn:
        await conn.execute(text("TRUNCATE TABLE news_items RESTART IDENTITY CASCADE"))


@pytest.fixture
async def db_session(migrated_db) -> AsyncSession:
    async with async_session_factory()() as session:
        yield session


@pytest.fixture
def repo(db_session: AsyncSession) -> NewsItemRepository:
    return NewsItemRepository(db_session)


async def _make_ready_with_plays(
    repo: NewsItemRepository,
    db_session: AsyncSession,
    *,
    plays: int,
) -> NewsItem:
    item = await repo.create_from_fetch(
        NewsFetchInput(
            source_url="https://example.com/reset-test",
            content_hash="reset-hash",
        )
    )
    await repo.update_summary(item.id, "Сводка для проверки сброса счётчика воспроизведений.")
    await repo.update_audio(item.id, "file:///data/news/reset-hash.mp3")
    await repo.mark_ready(item.id)
    for _ in range(plays):
        await repo.increment_play_count(
            item.id,
            played_at=datetime(2026, 6, 10, 12, 0, tzinfo=UTC),
        )
    await db_session.commit()
    reloaded = await repo.get_by_id(item.id)
    assert reloaded is not None
    return reloaded


def test_redis_increment_sets_ttl(redis_client: redis.Redis):
    count = increment_played_count(redis_client, "abc123")
    assert count == 1
    assert get_played_count(redis_client, "abc123") == 1

    ttl = redis_client.ttl(played_key("abc123"))
    assert 0 < ttl <= PLAYED_TTL_SEC

    count2 = increment_played_count(redis_client, "abc123")
    assert count2 == 2
    assert is_at_play_cap(redis_client, "abc123", cap=3) is False

    increment_played_count(redis_client, "abc123")
    assert is_at_play_cap(redis_client, "abc123", cap=3) is True


def test_clear_played_keys(redis_client: redis.Redis):
    increment_played_count(redis_client, "one")
    increment_played_count(redis_client, "two")
    assert get_played_count(redis_client, "one") == 1

    deleted = clear_played_keys(redis_client)
    assert deleted == 2
    assert get_played_count(redis_client, "one") == 0


@pytest.mark.asyncio
async def test_reset_postgres_play_counts(
    repo: NewsItemRepository,
    db_session: AsyncSession,
):
    item = await _make_ready_with_plays(repo, db_session, plays=2)
    item_id = item.id
    assert item.play_count == 2
    assert item.last_played_at is not None

    reset_count = await reset_postgres_play_counts(async_session_factory)
    assert reset_count == 1

    db_session.expunge_all()
    result = await db_session.execute(select(NewsItem).where(NewsItem.id == item_id))
    reloaded = result.scalar_one()
    assert reloaded.play_count == 0
    assert reloaded.last_played_at is None


@pytest.mark.asyncio
async def test_play_count_reset_worker_clears_pg_and_redis(
    repo: NewsItemRepository,
    db_session: AsyncSession,
    redis_client: redis.Redis,
):
    item = await _make_ready_with_plays(repo, db_session, plays=3)
    item_id = item.id
    increment_played_count(redis_client, "reset-hash")
    increment_played_count(redis_client, "reset-hash")

    worker = PlayCountResetWorker(
        session_factory=async_session_factory,
        redis_factory=lambda: redis_client,
    )
    pg_reset, redis_deleted = await worker.run_once()

    assert pg_reset == 1
    assert redis_deleted == 1
    assert get_played_count(redis_client, "reset-hash") == 0

    db_session.expunge_all()
    result = await db_session.execute(select(NewsItem).where(NewsItem.id == item_id))
    reloaded = result.scalar_one()
    assert reloaded.play_count == 0


def test_seconds_until_next_midnight_utc():
    just_before = datetime(2026, 6, 11, 23, 59, 30, tzinfo=UTC)
    assert 0 < seconds_until_next_midnight_utc(now=just_before) <= 30

    at_midnight = datetime(2026, 6, 12, 0, 0, 0, tzinfo=UTC)
    assert seconds_until_next_midnight_utc(now=at_midnight) == pytest.approx(
        timedelta(days=1).total_seconds(),
        abs=1,
    )
