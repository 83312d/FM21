"""Music buffer worker tests (U12)."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from services.db.migrate import run_migrations
from services.db.session import async_session_factory, reset_engine
from services.injector.main import app
from services.injector.queue import QueueClient
from services.music.buffer_worker import MusicBufferWorker
from services.music.provider import MusicProvider, ProviderUnavailable, StreamUrl, TrackInfo
from services.music.static_provider import StaticProvider

pytestmark = pytest.mark.usefixtures("migrated_db")

STATIC_MUSIC_DIR = Path(__file__).parent.parent / "data" / "music" / "static"
BUFFER_TARGET = 10


class FakeCatalogProvider(MusicProvider):
    """Returns N synthetic tracks that resolve to static bed files."""

    def __init__(self, static: StaticProvider, *, count: int = 20) -> None:
        self._static = static
        self._tracks = [
            TrackInfo(
                track_id=f"track-{i:02d}",
                title=f"Track {i}",
                artist="Test Artist",
                duration_sec=120,
            )
            for i in range(count)
        ]

    async def search(self, query: str, *, limit: int = 10) -> list[TrackInfo]:
        return self._tracks[:limit]

    async def get_playlist_tracks(self, playlist_id: str) -> list[TrackInfo]:
        return self._tracks

    async def resolve_stream_url(self, track_id: str) -> StreamUrl:
        if track_id.startswith("bed-"):
            return await self._static.resolve_stream_url(track_id)
        index = int(track_id.removeprefix("track-"))
        bed_id = f"bed-{(index % 5) + 1:02d}"
        return await self._static.resolve_stream_url(bed_id)


@pytest.fixture(autouse=True)
def _reset_engine():
    reset_engine()
    yield
    reset_engine()


@pytest.fixture
async def migrated_db():
    await run_migrations()
    yield
    from sqlalchemy import text
    from services.db.session import get_engine

    engine = get_engine()
    async with engine.begin() as conn:
        await conn.execute(text("TRUNCATE TABLE playlist_config RESTART IDENTITY CASCADE"))


@pytest.fixture
async def db_session(migrated_db) -> AsyncSession:
    async with async_session_factory()() as session:
        yield session


@pytest.fixture(autouse=True)
def injector_http(monkeypatch: pytest.MonkeyPatch):
    class _TestAsyncClient(AsyncClient):
        def __init__(self, *args, **kwargs):
            kwargs["transport"] = ASGITransport(app=app)
            kwargs["base_url"] = "http://testserver"
            super().__init__(*args, **kwargs)

    monkeypatch.setattr("services.music.enqueue.httpx.AsyncClient", _TestAsyncClient)


@pytest.fixture
def buffer_worker(
    queue_client: QueueClient,
    active_cities: list[str],
    injector_client,
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.setenv("STATIC_MUSIC_DIR", str(STATIC_MUSIC_DIR))
    monkeypatch.setenv("INJECTOR_URL", "http://testserver")
    monkeypatch.setenv("INTERNAL_ENQUEUE_TOKEN", "test-internal-token")
    static = StaticProvider(music_dir=STATIC_MUSIC_DIR)
    fake_provider = FakeCatalogProvider(static)

    async def _fake_create_provider(session=None):
        return fake_provider

    with patch(
        "services.music.buffer_worker.create_music_provider",
        side_effect=_fake_create_provider,
    ):
        yield MusicBufferWorker(
            queue=queue_client,
            active_cities=active_cities,
            buffer_target=BUFFER_TARGET,
        )


@pytest.mark.asyncio
async def test_empty_queue_fills_to_target(buffer_worker: MusicBufferWorker, queue_client: QueueClient):
    added = await buffer_worker.fill_city("moscow")
    assert added == BUFFER_TARGET
    assert queue_client.count_pending_music("moscow") == BUFFER_TARGET

    items = queue_client.list_items("moscow")
    assert all(item["type"] == "MUSIC" for item in items)
    assert all(item["priority"] == 10 for item in items)
    assert all(item["meta"]["duration_sec"] >= 1 for item in items)
    assert all(item["uri"].startswith("file://") for item in items)


@pytest.mark.asyncio
async def test_consumption_replenishes(buffer_worker: MusicBufferWorker, queue_client: QueueClient):
    await buffer_worker.fill_city("moscow")
    assert queue_client.count_pending_music("moscow") == BUFFER_TARGET

    for _ in range(3):
        queue_client._redis.rpop(queue_client.queue_key("moscow"))

    assert queue_client.count_pending_music("moscow") == BUFFER_TARGET - 3
    added = await buffer_worker.fill_city("moscow")
    assert added == 3
    assert queue_client.count_pending_music("moscow") == BUFFER_TARGET


@pytest.mark.asyncio
async def test_provider_failure_uses_static_fallback(
    queue_client: QueueClient,
    active_cities: list[str],
    injector_client,
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.setenv("STATIC_MUSIC_DIR", str(STATIC_MUSIC_DIR))
    monkeypatch.setenv("INJECTOR_URL", "http://testserver")
    monkeypatch.setenv("INTERNAL_ENQUEUE_TOKEN", "test-internal-token")

    static = StaticProvider(music_dir=STATIC_MUSIC_DIR)

    async def _static_only(session=None):
        return static

    with patch(
        "services.music.buffer_worker.create_music_provider",
        side_effect=_static_only,
    ):
        worker = MusicBufferWorker(
            queue=queue_client,
            active_cities=active_cities,
            buffer_target=5,
        )
        added = await worker.fill_city("moscow")

    assert added == 5
    items = queue_client.list_items("moscow")
    assert len(items) == 5
    assert all(item["uri"].startswith("file://") for item in items)
    assert all(item["meta"]["artist"] == "FM21 Static" for item in items)


@pytest.mark.asyncio
async def test_replenish_rotates_catalog_cursor(
    buffer_worker: MusicBufferWorker,
    queue_client: QueueClient,
    monkeypatch: pytest.MonkeyPatch,
):
    """Repeated single-track replenishment must not flood the queue with catalog[0]."""
    monkeypatch.setenv("STATIC_MUSIC_DIR", str(STATIC_MUSIC_DIR))
    worker = MusicBufferWorker(
        queue=buffer_worker._queue,
        active_cities=buffer_worker._active_cities,
        buffer_target=3,
    )
    await worker.fill_city("moscow")

    for _ in range(15):
        queue_client._redis.rpop(queue_client.queue_key("moscow"))
        await worker.fill_city("moscow")

    track_ids = [item["meta"]["track_id"] for item in queue_client.list_items("moscow")]
    assert len(track_ids) == 3
    assert len(set(track_ids)) == 3


@pytest.mark.asyncio
async def test_dedupe_skips_playlist_buffer(buffer_worker: MusicBufferWorker, queue_client: QueueClient):
    queue_client.record_playlist_buffer("moscow", "bed-01")
    await buffer_worker.fill_city("moscow")

    track_ids = [item["meta"]["track_id"] for item in queue_client.list_items("moscow")]
    assert "bed-01" not in track_ids
    assert len(track_ids) == BUFFER_TARGET


@pytest.mark.asyncio
async def test_playlist_change_purges_stale_music(
    queue_client: QueueClient,
    active_cities: list[str],
):
    from services.music.rules_schema import ResolvedCityRules

    worker = MusicBufferWorker(queue=queue_client, active_cities=active_cities, buffer_target=10)
    queue_client.enqueue_item(
        "moscow",
        {
            "type": "MUSIC",
            "uri": "file:///old.mp3",
            "priority": 10,
            "meta": {"title": "Old", "artist": "Old", "duration_sec": 120, "track_id": "old-1"},
        },
    )
    queue_client.enqueue_ad(
        "moscow",
        {
            "type": "AD",
            "uri": "file:///ad.mp3",
            "priority": 100,
            "meta": {"title": "Ad", "artist": "", "duration_sec": 30},
        },
    )
    queue_client.set_playlist_fingerprint("moscow", "111:1")

    rules = ResolvedCityRules(
        city_tag="moscow",
        yandex_playlist_ids=("222:2",),
        max_track_duration_sec=420,
        blocklisted_artists=frozenset(),
    )
    removed = worker._sync_playlist_catalog("moscow", rules)

    assert removed == 1
    assert queue_client.count_pending_music("moscow") == 0
    assert queue_client.count_pending_ads("moscow") == 1
    assert queue_client.get_playlist_fingerprint("moscow") == "222:2"


def test_enqueue_music_via_injector(injector_client, auth_headers, queue_client):
    payload = {
        "type": "MUSIC",
        "uri": "file:///data/music/static/bed-01.mp3",
        "city_tag": "moscow",
        "meta": {
            "title": "Bed One",
            "artist": "FM21 Static",
            "duration_sec": 120,
            "track_id": "bed-01",
        },
    }
    response = injector_client.post("/internal/enqueue", json=payload, headers=auth_headers)
    assert response.status_code == 201

    items = queue_client.list_items("moscow")
    assert len(items) == 1
    assert items[0]["type"] == "MUSIC"
    assert queue_client.list_playlist_buffer("moscow") == []
