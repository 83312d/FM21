"""News materialize pipeline and slot clock tests (U20)."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest
import redis
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from services.db.migrate import run_migrations
from services.db.models import NewsItemStatus
from services.db.session import async_session_factory, get_engine, reset_engine
from services.news.db.models import NewsFetchInput
from services.news.db.repository import NewsItemRepository
from services.news.pipeline import (
    MaterializeResult,
    get_pinned_item_id,
    materialize_news_item,
    pin_slot_item,
    select_for_materialize,
    slot_pin_key,
)
from services.news.slot_clock import (
    enqueue_slot_for_materialize,
    next_materialize_at,
    seconds_until_next_materialize,
    slot_iso,
)
from services.news.summarizer.validate import count_words
from services.news.tts.auth import SaluteSpeechAuth
from services.news.tts.salutespeech import SaluteSpeechTTS
from services.news.workers.materialize_cron import NewsMaterializeWorker

REPO_ROOT = Path(__file__).resolve().parents[1]


def _ru_words(count: int, word: str = "слово") -> str:
    return " ".join([word] * count)


@dataclass
class MockSummarizerClient:
    responses: list[str] = field(default_factory=list)
    calls: list[bool] = field(default_factory=list)

    async def summarize(self, source_text: str, *, tightened: bool = False) -> str:
        self.calls.append(tightened)
        if not self.responses:
            raise AssertionError("MockSummarizerClient has no more responses")
        return self.responses.pop(0)


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


@pytest.fixture
def news_dir(tmp_path: Path) -> Path:
    target = tmp_path / "news"
    target.mkdir()
    return target


@pytest.fixture
def mock_wav_bytes() -> bytes:
    import subprocess

    wav_path = Path("/tmp/fm21-test-materialize.wav")
    subprocess.run(
        [
            "ffmpeg",
            "-hide_banner",
            "-loglevel",
            "error",
            "-y",
            "-f",
            "lavfi",
            "-i",
            "sine=frequency=440:duration=0.5",
            str(wav_path),
        ],
        check=True,
        capture_output=True,
    )
    return wav_path.read_bytes()


@pytest.fixture
def mock_redis() -> MagicMock:
    store: dict[str, str] = {}
    client = MagicMock()

    def _get(key: str) -> str | None:
        return store.get(key)

    def _set(key: str, value: str, ex: int | None = None) -> None:
        store[key] = value

    client.get.side_effect = _get
    client.set.side_effect = _set
    client._store = store
    return client


@pytest.fixture
def tts_client(news_dir: Path, mock_redis: MagicMock, mock_wav_bytes: bytes) -> SaluteSpeechTTS:
    from services.news.storage.local import LocalNewsStorage

    storage = LocalNewsStorage(news_dir)
    http_client = AsyncMock(spec=httpx.AsyncClient)

    oauth_response = MagicMock()
    oauth_response.status_code = 200
    oauth_response.json.return_value = {"access_token": "test-token", "expires_in": 1800}

    synth_response = MagicMock()
    synth_response.status_code = 200
    synth_response.content = mock_wav_bytes

    async def _post(url: str, **kwargs):
        if "oauth" in url:
            return oauth_response
        if "text:synthesize" in url:
            return synth_response
        raise AssertionError(f"unexpected POST {url}")

    http_client.post.side_effect = _post

    auth = SaluteSpeechAuth(
        credentials="dGVzdDpzZWNyZXQ=",
        scope="SALUTE_SPEECH_PERS",
        verify_ssl=True,
        client=http_client,
    )
    return SaluteSpeechTTS(
        auth=auth,
        storage=storage,
        redis_client=mock_redis,
        client=http_client,
    )


def test_slot_clock_maps_materialize_to_enqueue():
    assert enqueue_slot_for_materialize(datetime(2026, 6, 11, 10, 2, tzinfo=UTC)) == datetime(
        2026, 6, 11, 10, 15, tzinfo=UTC
    )
    assert enqueue_slot_for_materialize(datetime(2026, 6, 11, 10, 17, tzinfo=UTC)) == datetime(
        2026, 6, 11, 10, 30, tzinfo=UTC
    )
    assert enqueue_slot_for_materialize(datetime(2026, 6, 11, 10, 32, tzinfo=UTC)) == datetime(
        2026, 6, 11, 10, 45, tzinfo=UTC
    )
    assert enqueue_slot_for_materialize(datetime(2026, 6, 11, 10, 47, tzinfo=UTC)) == datetime(
        2026, 6, 11, 11, 0, tzinfo=UTC
    )


def test_slot_iso_is_utc_zulu():
    slot = datetime(2026, 6, 11, 15, 0, tzinfo=UTC)
    assert slot_iso(slot) == "2026-06-11T15:00:00Z"


def test_next_materialize_and_sleep_window():
    now = datetime(2026, 6, 11, 10, 3, 30, tzinfo=UTC)
    assert next_materialize_at(now) == datetime(2026, 6, 11, 10, 17, tzinfo=UTC)
    assert seconds_until_next_materialize(now) == pytest.approx(13 * 60 + 30, rel=0.01)


@pytest.mark.asyncio
async def test_fetched_only_becomes_ready_before_enqueue_slot(
    repo: NewsItemRepository,
    db_session: AsyncSession,
    tts_client: SaluteSpeechTTS,
    mock_redis: MagicMock,
):
    item = await repo.create_from_fetch(
        NewsFetchInput(source_url="https://example.com/materialize-1", content_hash="hash-m1")
    )
    await db_session.commit()

    summarizer = MockSummarizerClient(responses=[_ru_words(180)])
    http_client = AsyncMock(spec=httpx.AsyncClient)
    article_response = MagicMock()
    article_response.text = "<html><body><p>Article body for summarization.</p></body></html>"
    article_response.raise_for_status = MagicMock()
    http_client.get.return_value = article_response

    materialize_at = datetime(2026, 6, 11, 10, 2, tzinfo=UTC)
    enqueue_at = enqueue_slot_for_materialize(materialize_at)
    assert enqueue_at > materialize_at

    result = await materialize_news_item(
        repo,
        item.id,
        summarizer_client=summarizer,
        tts_client=tts_client,
        http_client=http_client,
    )
    await db_session.commit()

    assert result is MaterializeResult.MATERIALIZED
    updated = await repo.get_by_id(item.id)
    assert updated is not None
    assert updated.status == NewsItemStatus.READY
    assert updated.summary_ru is not None
    assert count_words(updated.summary_ru) == 180
    assert updated.audio_url is not None
    assert summarizer.calls == [False]
    assert tts_client._client.post.await_count >= 1


@pytest.mark.asyncio
async def test_already_ready_skips_summarizer_and_tts(
    repo: NewsItemRepository,
    db_session: AsyncSession,
    tts_client: SaluteSpeechTTS,
):
    item = await repo.create_from_fetch(
        NewsFetchInput(source_url="https://example.com/materialize-ready", content_hash="hash-m2")
    )
    await db_session.commit()
    await repo.update_summary(item.id, _ru_words(180))
    await repo.update_audio(item.id, "file:///tmp/existing.mp3")
    await repo.mark_ready(item.id)
    await db_session.commit()

    summarizer = MockSummarizerClient(responses=[_ru_words(200)])
    http_client = AsyncMock(spec=httpx.AsyncClient)

    result = await materialize_news_item(
        repo,
        item.id,
        summarizer_client=summarizer,
        tts_client=tts_client,
        http_client=http_client,
    )

    assert result is MaterializeResult.READY
    assert summarizer.calls == []
    synth_calls = [
        call
        for call in tts_client._client.post.await_args_list
        if call.args and "text:synthesize" in str(call.args[0])
    ]
    assert synth_calls == []


@pytest.mark.asyncio
async def test_slot_pin_redis_key_per_city(
    redis_client: redis.Redis,
    repo: NewsItemRepository,
    db_session: AsyncSession,
    tts_client: SaluteSpeechTTS,
):
    item = await repo.create_from_fetch(
        NewsFetchInput(source_url="https://example.com/pin", content_hash="hash-pin")
    )
    await db_session.commit()
    await repo.update_summary(item.id, _ru_words(180))
    await repo.update_audio(item.id, "file:///tmp/pin.mp3")
    await repo.mark_ready(item.id)
    await db_session.commit()

    slot_key = slot_iso(datetime(2026, 6, 11, 10, 15, tzinfo=UTC))
    pin_slot_item(redis_client, "moscow", slot_key, item.id)

    assert get_pinned_item_id(redis_client, "moscow", slot_key) == item.id
    assert get_pinned_item_id(redis_client, "spb", slot_key) is None
    assert redis_client.ttl(slot_pin_key("moscow", slot_key)) > 0


@pytest.mark.asyncio
async def test_materialize_worker_pins_all_cities(
    repo: NewsItemRepository,
    db_session: AsyncSession,
    redis_client: redis.Redis,
    tts_client: SaluteSpeechTTS,
):
    item = await repo.create_from_fetch(
        NewsFetchInput(source_url="https://example.com/worker", content_hash="hash-worker")
    )
    await db_session.commit()
    await repo.update_summary(item.id, _ru_words(180))
    await repo.update_audio(item.id, "file:///tmp/worker.mp3")
    await repo.mark_ready(item.id)
    await db_session.commit()

    worker = NewsMaterializeWorker(cities=["moscow", "spb"])
    now = datetime(2026, 6, 11, 10, 17, tzinfo=UTC)
    stats = await worker.run_once(
        now=now,
        summarizer_client=MockSummarizerClient(),
        tts_client=tts_client,
        redis_client=redis_client,
    )

    slot_key = slot_iso(enqueue_slot_for_materialize(now))
    assert stats.pinned == 2
    assert stats.ready == 2
    assert get_pinned_item_id(redis_client, "moscow", slot_key) == item.id
    assert get_pinned_item_id(redis_client, "spb", slot_key) == item.id


@pytest.mark.asyncio
async def test_select_for_materialize_prefers_ready_over_fetched(
    repo: NewsItemRepository,
    db_session: AsyncSession,
    redis_client: redis.Redis,
):
    fetched = await repo.create_from_fetch(
        NewsFetchInput(source_url="https://example.com/fetched", content_hash="hash-f")
    )
    ready = await repo.create_from_fetch(
        NewsFetchInput(source_url="https://example.com/ready", content_hash="hash-r")
    )
    await db_session.commit()
    await repo.update_summary(ready.id, _ru_words(180))
    await repo.update_audio(ready.id, "file:///tmp/ready.mp3")
    await repo.mark_ready(ready.id)
    await db_session.commit()

    selected = await select_for_materialize(repo, db_session, redis_client)
    assert selected is not None
    assert selected.id == ready.id
    assert selected.id != fetched.id
