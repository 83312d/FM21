"""News repository tests (U15)."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from services.db.migrate import run_migrations
from services.db.models import NewsItemStatus
from services.db.session import async_session_factory, get_engine, reset_engine
from services.news.db.models import InvalidNewsStatusTransition, NewsFetchInput
from services.news.db.repository import NewsItemRepository

pytestmark = pytest.mark.asyncio


@pytest.fixture(autouse=True)
def _reset_engine():
    reset_engine()
    yield
    reset_engine()


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


async def test_migration_adds_news_indexes(migrated_db):
    engine = get_engine()
    async with engine.connect() as conn:
        result = await conn.execute(
            text(
                """
                SELECT indexname
                FROM pg_indexes
                WHERE tablename = 'news_items'
                  AND indexname IN (
                    'idx_news_items_status',
                    'idx_news_items_play_count',
                    'idx_news_items_status_play_count',
                    'idx_news_items_content_hash'
                  )
                ORDER BY indexname
                """
            )
        )
        indexes = [row[0] for row in result.fetchall()]

    assert indexes == [
        "idx_news_items_content_hash",
        "idx_news_items_play_count",
        "idx_news_items_status",
        "idx_news_items_status_play_count",
    ]


async def test_create_from_fetch(repo: NewsItemRepository, db_session: AsyncSession):
    item = await repo.create_from_fetch(
        NewsFetchInput(
            source_url="https://example.com/article",
            content_hash="abc123",
        )
    )
    await db_session.commit()

    assert item.id is not None
    assert item.source_url == "https://example.com/article"
    assert item.content_hash == "abc123"
    assert item.status == NewsItemStatus.FETCHED
    assert item.play_count == 0
    assert item.summary_ru is None
    assert item.audio_url is None


async def test_happy_path_state_transitions(repo: NewsItemRepository, db_session: AsyncSession):
    item = await repo.create_from_fetch(
        NewsFetchInput(source_url="https://example.com/news-1", content_hash="hash-1")
    )
    await db_session.commit()

    summarized = await repo.update_summary(item.id, "Краткая сводка новости для эфира.")
    assert summarized.status == NewsItemStatus.SUMMARIZED
    assert summarized.summary_ru == "Краткая сводка новости для эфира."

    voiced = await repo.update_audio(item.id, "file:///data/news/hash-1.mp3")
    assert voiced.status == NewsItemStatus.VOICED
    assert voiced.audio_url == "file:///data/news/hash-1.mp3"

    ready = await repo.mark_ready(item.id)
    assert ready.status == NewsItemStatus.READY
    await db_session.commit()


async def test_invalid_state_transitions(repo: NewsItemRepository, db_session: AsyncSession):
    item = await repo.create_from_fetch(NewsFetchInput(source_url="https://example.com/bad"))
    await db_session.commit()

    with pytest.raises(InvalidNewsStatusTransition):
        await repo.update_audio(item.id, "file:///data/news/bad.mp3")

    with pytest.raises(InvalidNewsStatusTransition):
        await repo.mark_ready(item.id)

    await repo.update_summary(item.id, "Сводка")
    with pytest.raises(InvalidNewsStatusTransition):
        await repo.mark_ready(item.id)


async def test_mark_failed_from_pipeline_states(repo: NewsItemRepository, db_session: AsyncSession):
    fetched = await repo.create_from_fetch(NewsFetchInput(source_url="https://example.com/fail-1"))
    await db_session.commit()
    failed = await repo.mark_failed(fetched.id)
    assert failed.status == NewsItemStatus.FAILED

    item = await repo.create_from_fetch(NewsFetchInput(source_url="https://example.com/fail-2"))
    await db_session.commit()
    await repo.update_summary(item.id, "Сводка")
    failed = await repo.mark_failed(item.id)
    assert failed.status == NewsItemStatus.FAILED

    with pytest.raises(InvalidNewsStatusTransition):
        await repo.update_audio(item.id, "file:///data/news/fail-2.mp3")


async def test_increment_play_count_once_per_air_slot(
    repo: NewsItemRepository,
    db_session: AsyncSession,
):
    """Scheduler calls increment once after fan-out to all cities (U21)."""
    item = await repo.create_from_fetch(
        NewsFetchInput(source_url="https://example.com/air", content_hash="air-hash")
    )
    await db_session.commit()
    await repo.update_summary(item.id, "Новость для эфира.")
    await repo.update_audio(item.id, "file:///data/news/air.mp3")
    await repo.mark_ready(item.id)
    await db_session.commit()

    played_at = datetime(2026, 6, 11, 12, 0, tzinfo=UTC)
    updated = await repo.increment_play_count(item.id, played_at=played_at)
    await db_session.commit()

    assert updated.play_count == 1
    assert updated.last_played_at == played_at

    reloaded = await repo.get_by_id(item.id)
    assert reloaded is not None
    assert reloaded.play_count == 1


async def test_increment_play_count_requires_ready(repo: NewsItemRepository, db_session: AsyncSession):
    item = await repo.create_from_fetch(NewsFetchInput(source_url="https://example.com/not-ready"))
    await db_session.commit()

    with pytest.raises(InvalidNewsStatusTransition):
        await repo.increment_play_count(item.id)


async def test_get_by_source_url_and_content_hash(repo: NewsItemRepository, db_session: AsyncSession):
    await repo.create_from_fetch(
        NewsFetchInput(
            source_url="https://example.com/lookup",
            content_hash="lookup-hash",
        )
    )
    await db_session.commit()

    by_url = await repo.get_by_source_url("https://example.com/lookup")
    by_hash = await repo.get_by_content_hash("lookup-hash")

    assert by_url is not None
    assert by_hash is not None
    assert by_url.id == by_hash.id
