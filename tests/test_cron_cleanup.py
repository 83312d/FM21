"""Cron cleanup jobs — cache-cleanup, news-cache-reset, scheduler timing (U32)."""

from __future__ import annotations

import os
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
import redis
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from services.cron.cleanup_ads import cleanup_expired_ads
from services.cron.cleanup_tracks import cleanup_expired_tracks
from services.cron.news_cache_reset import NewsCacheResetWorker
from services.cron.scheduler import CronScheduler, run_cache_cleanup
from services.cron.timing import (
    CRON_CACHE_CLEANUP,
    CRON_NEWS_CACHE_RESET,
    is_cron_due,
    seconds_until_next_cron,
)
from services.db.migrate import run_migrations
from services.db.models import Ad, AdStatus, TrackCache
from services.db.session import async_session_factory, get_engine, reset_engine
from services.news.db.models import NewsFetchInput
from services.news.db.repository import NewsItemRepository
from services.news.play_count import increment_played_count
from services.news.workers.play_count_reset import reset_postgres_play_counts


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
        for table in ("tracks_cache", "ads", "news_items"):
            await conn.execute(text(f"TRUNCATE TABLE {table} RESTART IDENTITY CASCADE"))


@pytest.fixture
async def db_session(migrated_db) -> AsyncSession:
    async with async_session_factory()() as session:
        yield session


@pytest.fixture
def ads_dir(tmp_path: Path) -> Path:
    path = tmp_path / "ads"
    path.mkdir()
    return path


async def _seed_ad(
    db_session: AsyncSession,
    *,
    status: AdStatus,
    audio_path: Path | None = None,
) -> Ad:
    if audio_path is None:
        audio_path = Path(f"/data/ads/{status.value}-ad.mp3")
    ad = Ad(
        telegram_user_id=42,
        city_tag="moscow",
        audio_url=f"file://{audio_path}",
        status=status,
    )
    db_session.add(ad)
    await db_session.commit()
    await db_session.refresh(ad)
    return ad


@pytest.mark.asyncio
async def test_cleanup_expired_tracks_deletes_only_stale_rows(db_session: AsyncSession):
    now = datetime(2026, 6, 15, 3, 0, tzinfo=UTC)
    stale = TrackCache(
        yandex_track_id="stale-1",
        title="Old",
        artist="Artist",
        stream_url="https://cdn.example/stale.mp3",
        stream_url_expires=now - timedelta(hours=1),
    )
    fresh = TrackCache(
        yandex_track_id="fresh-1",
        title="New",
        artist="Artist",
        stream_url="https://cdn.example/fresh.mp3",
        stream_url_expires=now + timedelta(hours=2),
    )
    db_session.add_all([stale, fresh])
    await db_session.commit()

    deleted = await cleanup_expired_tracks(async_session_factory, now=now)
    assert deleted == 1

    remaining = (await db_session.execute(select(TrackCache))).scalars().all()
    assert [row.yandex_track_id for row in remaining] == ["fresh-1"]


@pytest.mark.asyncio
async def test_cleanup_expired_ads_removes_terminal_rows_and_files(
    db_session: AsyncSession,
    ads_dir: Path,
):
    played_file = ads_dir / "played.mp3"
    played_file.write_bytes(b"mp3")
    rejected_file = ads_dir / "rejected.mp3"
    rejected_file.write_bytes(b"mp3")
    pending_file = ads_dir / "pending.mp3"
    pending_file.write_bytes(b"mp3")

    played = await _seed_ad(
        db_session,
        status=AdStatus.PLAYED,
        audio_path=played_file,
    )
    rejected = await _seed_ad(
        db_session,
        status=AdStatus.REJECTED,
        audio_path=rejected_file,
    )
    pending = await _seed_ad(
        db_session,
        status=AdStatus.PENDING,
        audio_path=pending_file,
    )
    queued = await _seed_ad(
        db_session,
        status=AdStatus.QUEUED,
        audio_path=ads_dir / "queued.mp3",
    )

    rows_deleted, files_deleted = await cleanup_expired_ads(
        async_session_factory,
        ads_dir=ads_dir,
    )

    assert rows_deleted == 2
    assert files_deleted == 2
    assert not played_file.exists()
    assert not rejected_file.exists()
    assert pending_file.exists()

    remaining_ids = {
        row.id
        for row in (await db_session.execute(select(Ad))).scalars().all()
    }
    assert remaining_ids == {pending.id, queued.id}


@pytest.mark.asyncio
async def test_news_cache_reset_worker_delegates_to_play_count_reset(
    db_session: AsyncSession,
    redis_client: redis.Redis,
):
    repo = NewsItemRepository(db_session)
    item = await repo.create_from_fetch(
        NewsFetchInput(
            source_url="https://example.com/cron-reset",
            content_hash="cron-reset-hash",
        )
    )
    await repo.update_summary(item.id, "Сводка.")
    await repo.update_audio(item.id, "file:///data/news/cron-reset.mp3")
    await repo.mark_ready(item.id)
    await repo.increment_play_count(
        item.id,
        played_at=datetime(2026, 6, 14, 12, 0, tzinfo=UTC),
    )
    await db_session.commit()
    increment_played_count(redis_client, "cron-reset-hash")

    worker = NewsCacheResetWorker(
        session_factory=async_session_factory,
        redis_factory=lambda: redis_client,
    )
    pg_reset, redis_deleted = await worker.run_once()

    assert pg_reset == 1
    assert redis_deleted == 1
    assert await reset_postgres_play_counts(async_session_factory) == 0


@pytest.mark.asyncio
async def test_run_cache_cleanup_runs_both_jobs(
    db_session: AsyncSession,
    ads_dir: Path,
):
    now = datetime(2026, 6, 15, 3, 0, tzinfo=UTC)
    db_session.add(
        TrackCache(
            yandex_track_id="expired",
            title="T",
            artist="A",
            stream_url="https://cdn.example/x.mp3",
            stream_url_expires=now - timedelta(minutes=5),
        )
    )
    played_file = ads_dir / "played.mp3"
    played_file.write_bytes(b"mp3")
    db_session.add(
        Ad(
            telegram_user_id=1,
            city_tag="moscow",
            audio_url=f"file://{played_file}",
            status=AdStatus.PLAYED,
        )
    )
    await db_session.commit()

    tracks_deleted, ads_deleted, files_deleted = await run_cache_cleanup(
        async_session_factory,
        ads_dir=ads_dir,
        now=now,
    )

    assert tracks_deleted == 1
    assert ads_deleted == 1
    assert files_deleted == 1
    assert (await db_session.execute(select(TrackCache))).scalars().all() == []
    assert (await db_session.execute(select(Ad))).scalars().all() == []


def test_seconds_until_next_cron_cache_cleanup():
    before = datetime(2026, 6, 15, 2, 30, tzinfo=UTC)
    assert 0 < seconds_until_next_cron(CRON_CACHE_CLEANUP, now=before) <= 1800

    at_three = datetime(2026, 6, 15, 3, 0, tzinfo=UTC)
    assert seconds_until_next_cron(CRON_CACHE_CLEANUP, now=at_three) == pytest.approx(
        timedelta(days=1).total_seconds(),
        abs=1,
    )


def test_is_cron_due_at_scheduled_minute():
    midnight = datetime(2026, 6, 15, 0, 0, 30, tzinfo=UTC)
    assert is_cron_due(CRON_NEWS_CACHE_RESET, now=midnight) is True

    not_midnight = datetime(2026, 6, 15, 0, 1, 30, tzinfo=UTC)
    assert is_cron_due(CRON_NEWS_CACHE_RESET, now=not_midnight) is False


@pytest.mark.asyncio
async def test_scheduler_run_due_jobs_at_midnight(
    db_session: AsyncSession,
    redis_client: redis.Redis,
):
    repo = NewsItemRepository(db_session)
    item = await repo.create_from_fetch(
        NewsFetchInput(
            source_url="https://example.com/scheduler",
            content_hash="sched-hash",
        )
    )
    await repo.update_summary(item.id, "Сводка.")
    await repo.update_audio(item.id, "file:///data/news/sched.mp3")
    await repo.mark_ready(item.id)
    await repo.increment_play_count(
        item.id,
        played_at=datetime(2026, 6, 14, 12, 0, tzinfo=UTC),
    )
    await db_session.commit()

    scheduler = CronScheduler(
        session_factory=async_session_factory,
        redis_factory=lambda: redis_client,
        ads_dir=Path("/tmp/unused"),
    )
    results = await scheduler.run_due_jobs(
        now=datetime(2026, 6, 15, 0, 0, 15, tzinfo=UTC),
    )

    assert "news-cache-reset" in results
    assert results["news-cache-reset"]["pg_reset"] == 1


@pytest.mark.asyncio
async def test_scheduler_run_due_jobs_at_cache_cleanup_hour(
    db_session: AsyncSession,
    ads_dir: Path,
):
    now = datetime(2026, 6, 15, 3, 0, 10, tzinfo=UTC)
    db_session.add(
        TrackCache(
            yandex_track_id="gone",
            title="T",
            artist="A",
            stream_url="https://cdn.example/gone.mp3",
            stream_url_expires=now - timedelta(hours=1),
        )
    )
    await db_session.commit()

    scheduler = CronScheduler(
        session_factory=async_session_factory,
        ads_dir=ads_dir,
    )
    results = await scheduler.run_due_jobs(now=now)

    assert "cache-cleanup" in results
    assert results["cache-cleanup"]["tracks_deleted"] == 1
