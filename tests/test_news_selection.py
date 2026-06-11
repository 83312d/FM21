"""News selection tests — AE3 play cap skip and rotation (U19)."""

from __future__ import annotations

import os
from datetime import UTC, datetime

import pytest
import redis
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from services.db.migrate import run_migrations
from services.db.session import async_session_factory, get_engine, reset_engine
from services.news.db.models import NewsFetchInput
from services.news.db.repository import NewsItemRepository
from services.news.play_count import MAX_PLAYS_PER_24H, increment_played_count
from services.news.selection import list_ready_ordered, select_news_item

pytestmark = pytest.mark.asyncio


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


async def _make_ready(
    repo: NewsItemRepository,
    db_session: AsyncSession,
    *,
    source_url: str,
    content_hash: str,
    summary: str = "Сводка новости для эфира в нужном объёме слов.",
) -> int:
    item = await repo.create_from_fetch(
        NewsFetchInput(source_url=source_url, content_hash=content_hash)
    )
    await repo.update_summary(item.id, summary)
    await repo.update_audio(item.id, f"file:///data/news/{content_hash}.mp3")
    await repo.mark_ready(item.id)
    await db_session.commit()
    return item.id


async def test_select_skips_item_at_play_cap_when_alternatives_exist(
    repo: NewsItemRepository,
    db_session: AsyncSession,
    redis_client: redis.Redis,
):
    """AE3: capped item skipped; different eligible item selected."""
    capped_id = await _make_ready(
        repo,
        db_session,
        source_url="https://example.com/capped",
        content_hash="hash-capped",
    )
    fresh_id = await _make_ready(
        repo,
        db_session,
        source_url="https://example.com/fresh",
        content_hash="hash-fresh",
    )

    for _ in range(MAX_PLAYS_PER_24H):
        await repo.increment_play_count(capped_id)
    await db_session.commit()

    for _ in range(MAX_PLAYS_PER_24H):
        increment_played_count(redis_client, "hash-capped")

    selected = await select_news_item(repo, db_session, redis_client)
    assert selected is not None
    assert selected.id == fresh_id


async def test_select_rotates_by_last_played_at_nulls_first(
    repo: NewsItemRepository,
    db_session: AsyncSession,
    redis_client: redis.Redis,
):
    older_id = await _make_ready(
        repo,
        db_session,
        source_url="https://example.com/older",
        content_hash="hash-older",
    )
    newer_id = await _make_ready(
        repo,
        db_session,
        source_url="https://example.com/newer",
        content_hash="hash-newer",
    )

    await repo.increment_play_count(
        newer_id,
        played_at=datetime(2026, 6, 11, 10, 0, tzinfo=UTC),
    )
    await repo.increment_play_count(
        older_id,
        played_at=datetime(2026, 6, 11, 8, 0, tzinfo=UTC),
    )
    await db_session.commit()

    never_played_id = await _make_ready(
        repo,
        db_session,
        source_url="https://example.com/never",
        content_hash="hash-never",
    )

    selected = await select_news_item(repo, db_session, redis_client)
    assert selected is not None
    assert selected.id == never_played_id

    await repo.increment_play_count(
        never_played_id,
        played_at=datetime(2026, 6, 11, 12, 0, tzinfo=UTC),
    )
    await db_session.commit()

    selected_next = await select_news_item(repo, db_session, redis_client)
    assert selected_next is not None
    assert selected_next.id == older_id


async def test_select_fallback_when_all_at_cap(
    repo: NewsItemRepository,
    db_session: AsyncSession,
    redis_client: redis.Redis,
):
    """AE3: no alternatives — return ready item with cached audio_url."""
    only_id = await _make_ready(
        repo,
        db_session,
        source_url="https://example.com/only",
        content_hash="hash-only",
    )
    for _ in range(MAX_PLAYS_PER_24H):
        await repo.increment_play_count(only_id)
    await db_session.commit()

    selected = await select_news_item(repo, db_session, redis_client)
    assert selected is not None
    assert selected.id == only_id
    assert selected.audio_url is not None


async def test_list_ready_ordered_nulls_first(
    repo: NewsItemRepository,
    db_session: AsyncSession,
):
    id_a = await _make_ready(
        repo,
        db_session,
        source_url="https://example.com/a",
        content_hash="hash-a",
    )
    id_b = await _make_ready(
        repo,
        db_session,
        source_url="https://example.com/b",
        content_hash="hash-b",
    )
    await repo.increment_play_count(
        id_b,
        played_at=datetime(2026, 6, 11, 9, 0, tzinfo=UTC),
    )
    await db_session.commit()

    items = await list_ready_ordered(db_session)
    assert [item.id for item in items] == [id_a, id_b]
