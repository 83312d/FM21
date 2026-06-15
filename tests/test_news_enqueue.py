"""News enqueue cron — NEWS_PAIR fan-out and slip skip (U21)."""

from __future__ import annotations

import os
from datetime import UTC, datetime
from uuid import uuid4

import pytest
import redis
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from services.db.migrate import run_migrations
from services.db.models import NewsItemStatus
from services.db.session import async_session_factory, get_engine, reset_engine
from services.injector.queue import QueueClient
from services.news.db.models import NewsFetchInput
from services.news.db.repository import NewsItemRepository
from services.news.enqueue import (
    NewsEnqueueFailure,
    NewsEnqueueResult,
    build_news_pair_payload,
    estimate_slip_sec,
    resolve_duration_sec,
    should_skip_for_slip,
)
from services.news.pipeline import pin_slot_item
from services.news.play_count import get_played_count
from services.news.slot_clock import current_enqueue_slot, slot_iso
from services.news.workers.enqueue_cron import NewsEnqueueWorker

pytestmark = pytest.mark.usefixtures("queue_client")


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
async def repo(db_session: AsyncSession) -> NewsItemRepository:
    return NewsItemRepository(db_session)


@pytest.fixture
def enqueue_via_injector(injector_client, auth_headers, monkeypatch):
    async def _enqueue(payload: dict) -> NewsEnqueueResult | NewsEnqueueFailure:
        response = injector_client.post(
            "/internal/enqueue",
            json=payload,
            headers=auth_headers,
        )
        if response.status_code == 201:
            body = response.json()
            return NewsEnqueueResult(id=body["id"], city_tags=body["city_tags"])
        detail = response.json().get("detail")
        message = detail if isinstance(detail, str) else detail.get("message", "enqueue failed")
        city = detail.get("city_tag") if isinstance(detail, dict) else None
        return NewsEnqueueFailure(
            status_code=response.status_code,
            message=message,
            city_tag=city,
        )

    monkeypatch.setattr("services.news.workers.enqueue_cron.enqueue_news_pair", _enqueue)


async def _ready_item(
    repo: NewsItemRepository,
    db_session: AsyncSession,
    *,
    content_hash: str = "enqueue-hash",
) -> int:
    item = await repo.create_from_fetch(
        NewsFetchInput(
            source_url=f"https://example.com/{uuid4()}",
            content_hash=content_hash,
        )
    )
    await db_session.commit()
    await repo.update_summary(item.id, "Короткая новость для эфира.")
    await repo.update_audio(item.id, f"file:///data/news/{item.id}.mp3")
    await repo.mark_ready(item.id)
    await db_session.commit()
    return item.id


@pytest.mark.asyncio
async def test_build_news_pair_payload_uses_ceiled_probe_duration(
    repo: NewsItemRepository,
    db_session: AsyncSession,
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
):
    mp3_path = tmp_path / "fractional.mp3"
    mp3_path.write_bytes(b"\x00")

    item = await repo.create_from_fetch(
        NewsFetchInput(
            source_url="https://example.com/ceil-duration",
            content_hash="ceil-duration-hash",
        )
    )
    await db_session.commit()
    await repo.update_summary(item.id, "Новость с дробной длительностью.")
    await repo.update_audio(item.id, f"file://{mp3_path}")
    await repo.mark_ready(item.id)
    await db_session.commit()

    reloaded = await repo.get_by_id(item.id)
    assert reloaded is not None

    monkeypatch.setattr(
        "services.news.enqueue.probe_duration_sec",
        lambda path: 88.4,
    )

    assert resolve_duration_sec(reloaded.audio_url) == 89

    payload = build_news_pair_payload(reloaded)
    assert payload["meta"]["duration_sec"] == 89


@pytest.mark.asyncio
async def test_build_news_pair_payload_shape(repo: NewsItemRepository, db_session: AsyncSession):
    item_id = await _ready_item(repo, db_session)
    item = await repo.get_by_id(item_id)
    assert item is not None

    payload = build_news_pair_payload(item, duration_sec=90, stinger_uri="file:///data/news/news-stinger.mp3")

    assert payload == {
        "type": "NEWS_PAIR",
        "uri": f"file:///data/news/{item_id}.mp3",
        "city_tag": "all",
        "meta": {
            "title": "Короткая новость для эфира.",
            "duration_sec": 90,
            "stinger_uri": "file:///data/news/news-stinger.mp3",
        },
    }


@pytest.mark.asyncio
async def test_two_cities_one_play_count_increment(
    repo: NewsItemRepository,
    db_session: AsyncSession,
    redis_client: redis.Redis,
    queue_client: QueueClient,
    enqueue_via_injector,
):
    item_id = await _ready_item(repo, db_session, content_hash="fanout-hash")
    now = datetime(2026, 6, 11, 12, 0, tzinfo=UTC)
    slot_key = slot_iso(current_enqueue_slot(now))
    pin_slot_item(redis_client, "moscow", slot_key, item_id)
    pin_slot_item(redis_client, "spb", slot_key, item_id)

    worker = NewsEnqueueWorker(cities=["moscow", "spb"])
    stats = await worker.run_once(now=now, redis_client=redis_client)

    assert stats.enqueued is True
    assert stats.item_id == item_id
    assert stats.skipped_slip is False

    moscow_items = queue_client.list_items("moscow")
    spb_items = queue_client.list_items("spb")
    assert len(moscow_items) == 1
    assert len(spb_items) == 1
    assert moscow_items[0]["type"] == "NEWS_PAIR"
    assert spb_items[0]["type"] == "NEWS_PAIR"
    assert moscow_items[0]["priority"] == 80
    assert moscow_items[0]["meta"]["stinger_uri"].endswith("news-stinger.mp3")
    assert moscow_items[0]["uri"] == f"file:///data/news/{item_id}.mp3"
    assert moscow_items[0]["id"] != spb_items[0]["id"]

    reloaded = await repo.get_by_id(item_id)
    assert reloaded is not None
    assert reloaded.play_count == 1
    assert reloaded.last_played_at == now
    assert get_played_count(redis_client, "fanout-hash") == 1


@pytest.mark.asyncio
async def test_slip_over_ten_minutes_skips_enqueue(
    repo: NewsItemRepository,
    db_session: AsyncSession,
    redis_client: redis.Redis,
    queue_client: QueueClient,
    enqueue_via_injector,
):
    item_id = await _ready_item(repo, db_session)
    now = datetime(2026, 6, 11, 12, 0, tzinfo=UTC)
    slot_key = slot_iso(current_enqueue_slot(now))
    pin_slot_item(redis_client, "moscow", slot_key, item_id)
    pin_slot_item(redis_client, "spb", slot_key, item_id)

    ad_item = {
        "type": "AD",
        "priority": 100,
        "uri": "file:///data/ads/backlog.mp3",
        "city_tag": "moscow",
        "meta": {"title": "Ad", "artist": "", "duration_sec": 60},
    }
    for _ in range(11):
        queue_client.enqueue_item("moscow", {**ad_item, "id": str(uuid4())})

    slip = estimate_slip_sec(
        redis_client,
        queue_client,
        "moscow",
        slot=current_enqueue_slot(now),
        now=now,
    )
    assert slip >= 660

    worker = NewsEnqueueWorker(cities=["moscow", "spb"])
    stats = await worker.run_once(now=now, redis_client=redis_client)

    assert stats.skipped_slip is True
    assert stats.enqueued is False
    assert all(i["type"] == "AD" for i in queue_client.list_items("moscow"))
    news_pairs = [
        i
        for city in ("moscow", "spb")
        for i in queue_client.list_items(city)
        if i["type"] == "NEWS_PAIR"
    ]
    assert news_pairs == []

    reloaded = await repo.get_by_id(item_id)
    assert reloaded is not None
    assert reloaded.play_count == 0


def test_should_skip_for_slip_uses_worst_city(queue_client: QueueClient, redis_client: redis.Redis):
    now = datetime(2026, 6, 11, 12, 0, tzinfo=UTC)
    slot = current_enqueue_slot(now)

    ad_item = {
        "type": "AD",
        "priority": 100,
        "uri": "file:///data/ads/a.mp3",
        "city_tag": "moscow",
        "meta": {"title": "Ad", "artist": "", "duration_sec": 60},
    }
    queue_client.enqueue_item("moscow", {**ad_item, "id": str(uuid4())})

    skip, city = should_skip_for_slip(
        redis_client,
        queue_client,
        ["moscow", "spb"],
        slot=slot,
        now=now,
        max_slip_sec=600,
    )
    assert skip is False
    assert city is None

    for _ in range(10):
        queue_client.enqueue_item("moscow", {**ad_item, "id": str(uuid4())})

    skip, city = should_skip_for_slip(
        redis_client,
        queue_client,
        ["moscow", "spb"],
        slot=slot,
        now=now,
        max_slip_sec=600,
    )
    assert skip is True
    assert city == "moscow"


def test_injector_accepts_news_pair_all_fanout(
    injector_client,
    auth_headers,
    queue_client: QueueClient,
    active_cities: list[str],
):
    payload = {
        "type": "NEWS_PAIR",
        "uri": "file:///data/news/42.mp3",
        "city_tag": "all",
        "meta": {
            "title": "IT news headline",
            "duration_sec": 90,
            "stinger_uri": "file:///data/news/news-stinger.mp3",
        },
    }
    response = injector_client.post("/internal/enqueue", json=payload, headers=auth_headers)
    assert response.status_code == 201
    body = response.json()
    assert set(body["city_tags"]) == set(active_cities)

    for city in active_cities:
        items = queue_client.list_items(city)
        assert len(items) == 1
        assert items[0]["type"] == "NEWS_PAIR"
        assert items[0]["meta"]["stinger_uri"] == "file:///data/news/news-stinger.mp3"
