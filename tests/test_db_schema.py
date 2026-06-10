"""PostgreSQL schema tests (U9)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import delete, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from services.db.migrate import run_migrations
from services.db.models import (
    Ad,
    AdStatus,
    BroadcastLog,
    NewsItem,
    NewsItemStatus,
    PlaylistConfig,
    TrackCache,
)
from services.db.session import async_session_factory, get_engine, reset_engine

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
        for table in (
            "broadcast_log",
            "playlist_config",
            "tracks_cache",
            "ads",
            "news_items",
        ):
            await conn.execute(text(f"TRUNCATE TABLE {table} RESTART IDENTITY CASCADE"))


@pytest.fixture
async def db_session(migrated_db) -> AsyncSession:
    async with async_session_factory()() as session:
        yield session


async def test_migration_applies_fresh(migrated_db):
    engine = get_engine()
    async with engine.connect() as conn:
        result = await conn.execute(
            text(
                """
                SELECT table_name
                FROM information_schema.tables
                WHERE table_schema = 'public'
                  AND table_name IN (
                    'news_items', 'ads', 'tracks_cache',
                    'playlist_config', 'broadcast_log', 'schema_migrations'
                  )
                ORDER BY table_name
                """
            )
        )
        tables = [row[0] for row in result.fetchall()]

    assert tables == [
        "ads",
        "broadcast_log",
        "news_items",
        "playlist_config",
        "schema_migrations",
        "tracks_cache",
    ]


async def test_migration_is_idempotent(migrated_db):
    applied_again = await run_migrations()
    assert applied_again == []


async def test_news_items_unique_source_url(db_session: AsyncSession):
    db_session.add(
        NewsItem(
            source_url="https://example.com/a",
            content_hash="hash-a",
            status=NewsItemStatus.FETCHED,
        )
    )
    await db_session.commit()

    db_session.add(
        NewsItem(
            source_url="https://example.com/a",
            content_hash="hash-b",
            status=NewsItemStatus.FETCHED,
        )
    )
    with pytest.raises(IntegrityError):
        await db_session.commit()
    await db_session.rollback()


async def test_news_items_unique_content_hash(db_session: AsyncSession):
    db_session.add(
        NewsItem(
            source_url="https://example.com/one",
            content_hash="shared-hash",
            status=NewsItemStatus.FETCHED,
        )
    )
    await db_session.commit()

    db_session.add(
        NewsItem(
            source_url="https://example.com/two",
            content_hash="shared-hash",
            status=NewsItemStatus.FETCHED,
        )
    )
    with pytest.raises(IntegrityError):
        await db_session.commit()
    await db_session.rollback()


async def test_news_items_crud(db_session: AsyncSession):
    now = datetime.now(UTC)
    item = NewsItem(
        source_url="https://example.com/news",
        summary_ru="Краткая сводка",
        audio_url="file:///data/news/item.mp3",
        play_count=1,
        last_played_at=now,
        status=NewsItemStatus.READY,
        content_hash="news-hash-1",
    )
    db_session.add(item)
    await db_session.commit()

    row = (
        await db_session.execute(select(NewsItem).where(NewsItem.source_url == item.source_url))
    ).scalar_one()
    assert row.summary_ru == "Краткая сводка"
    assert row.status == NewsItemStatus.READY

    row.play_count = 2
    await db_session.commit()

    updated = (await db_session.execute(select(NewsItem).where(NewsItem.id == row.id))).scalar_one()
    assert updated.play_count == 2

    await db_session.execute(delete(NewsItem).where(NewsItem.id == row.id))
    await db_session.commit()
    assert (await db_session.execute(select(NewsItem).where(NewsItem.id == row.id))).scalar_one_or_none() is None


async def test_ads_crud(db_session: AsyncSession):
    ad = Ad(
        telegram_user_id=12345,
        city_tag="moscow",
        audio_url="file:///data/ads/voice.mp3",
        status=AdStatus.QUEUED,
    )
    db_session.add(ad)
    await db_session.commit()

    row = (await db_session.execute(select(Ad).where(Ad.id == ad.id))).scalar_one()
    assert row.city_tag == "moscow"

    row.status = AdStatus.PLAYED
    await db_session.commit()

    updated = (await db_session.execute(select(Ad).where(Ad.id == ad.id))).scalar_one()
    assert updated.status == AdStatus.PLAYED

    await db_session.execute(delete(Ad).where(Ad.id == ad.id))
    await db_session.commit()
    assert (await db_session.execute(select(Ad).where(Ad.id == ad.id))).scalar_one_or_none() is None


async def test_tracks_cache_crud(db_session: AsyncSession):
    expires = datetime.now(UTC) + timedelta(hours=1)
    track = TrackCache(
        yandex_track_id="track-42",
        title="Test Song",
        artist="Test Artist",
        stream_url="https://cdn.example/track.mp3",
        stream_url_expires=expires,
    )
    db_session.add(track)
    await db_session.commit()

    row = (
        await db_session.execute(
            select(TrackCache).where(TrackCache.yandex_track_id == "track-42")
        )
    ).scalar_one()
    assert row.stream_url.endswith("track.mp3")

    row.title = "Updated Song"
    await db_session.commit()

    updated = (
        await db_session.execute(
            select(TrackCache).where(TrackCache.yandex_track_id == "track-42")
        )
    ).scalar_one()
    assert updated.title == "Updated Song"

    await db_session.execute(
        delete(TrackCache).where(TrackCache.yandex_track_id == "track-42")
    )
    await db_session.commit()
    assert (
        await db_session.execute(
            select(TrackCache).where(TrackCache.yandex_track_id == "track-42")
        )
    ).scalar_one_or_none() is None


async def test_playlist_config_crud(db_session: AsyncSession):
    config = PlaylistConfig(
        city_tag="moscow",
        rules_json={"genre": "electronic", "bpm_min": 120},
    )
    db_session.add(config)
    await db_session.commit()

    row = (
        await db_session.execute(
            select(PlaylistConfig).where(PlaylistConfig.city_tag == "moscow")
        )
    ).scalar_one()
    assert row.rules_json["genre"] == "electronic"

    row.rules_json = {"genre": "ambient"}
    await db_session.commit()

    updated = (
        await db_session.execute(
            select(PlaylistConfig).where(PlaylistConfig.city_tag == "moscow")
        )
    ).scalar_one()
    assert updated.rules_json["genre"] == "ambient"

    await db_session.execute(delete(PlaylistConfig).where(PlaylistConfig.city_tag == "moscow"))
    await db_session.commit()
    assert (
        await db_session.execute(
            select(PlaylistConfig).where(PlaylistConfig.city_tag == "moscow")
        )
    ).scalar_one_or_none() is None


async def test_broadcast_log_crud(db_session: AsyncSession):
    started = datetime.now(UTC)
    ended = started + timedelta(minutes=3)
    entry = BroadcastLog(
        city_tag="spb",
        item_type="AD",
        started_at=started,
        ended_at=ended,
    )
    db_session.add(entry)
    await db_session.commit()

    row = (await db_session.execute(select(BroadcastLog).where(BroadcastLog.id == entry.id))).scalar_one()
    assert row.item_type == "AD"

    row.ended_at = ended + timedelta(seconds=30)
    await db_session.commit()

    updated = (
        await db_session.execute(select(BroadcastLog).where(BroadcastLog.id == entry.id))
    ).scalar_one()
    assert updated.ended_at == ended + timedelta(seconds=30)

    await db_session.execute(delete(BroadcastLog).where(BroadcastLog.id == entry.id))
    await db_session.commit()
    assert (
        await db_session.execute(select(BroadcastLog).where(BroadcastLog.id == entry.id))
    ).scalar_one_or_none() is None
