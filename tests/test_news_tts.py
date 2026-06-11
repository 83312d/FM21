"""SaluteSpeech TTS, storage, and stinger tests (U18)."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from services.db.migrate import run_migrations
from services.db.models import NewsItemStatus
from services.db.session import async_session_factory, get_engine, reset_engine
from services.news.audio_probe import probe_duration_sec
from services.news.db.models import NewsFetchInput
from services.news.db.repository import NewsItemRepository
from services.news.storage.local import LocalNewsStorage
from services.news.tts.auth import SaluteSpeechAuth
from services.news.tts.salutespeech import (
    SaluteSpeechTTS,
    summary_cache_key,
    wav_bytes_to_mp3,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
STINGER_PATH = REPO_ROOT / "data" / "news" / "news-stinger.mp3"


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


@pytest.fixture
def news_dir(tmp_path: Path) -> Path:
    target = tmp_path / "news"
    target.mkdir()
    return target


@pytest.fixture
def mock_wav_bytes() -> bytes:
    """Minimal valid WAV (silence) generated via ffmpeg in the test container."""
    import subprocess

    wav_path = Path("/tmp/fm21-test-tts.wav")
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

    def _set(key: str, value: str) -> None:
        store[key] = value

    client.get.side_effect = _get
    client.set.side_effect = _set
    client._store = store
    return client


@pytest.fixture
def tts_client(news_dir: Path, mock_redis: MagicMock, mock_wav_bytes: bytes) -> SaluteSpeechTTS:
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


async def _seed_summarized_item(
    repo: NewsItemRepository,
    db_session: AsyncSession,
    *,
    source_url: str,
    summary_ru: str,
) -> int:
    item = await repo.create_from_fetch(NewsFetchInput(source_url=source_url))
    await db_session.commit()
    await repo.update_summary(item.id, summary_ru)
    await db_session.commit()
    return item.id


@pytest.mark.asyncio
async def test_voice_news_item_writes_file_and_updates_repo(
    tts_client: SaluteSpeechTTS,
    repo: NewsItemRepository,
    db_session: AsyncSession,
    news_dir: Path,
):
    summary = "Краткая сводка новости для озвучивания в эфире."
    item_id = await _seed_summarized_item(
        repo,
        db_session,
        source_url="https://example.com/tts-1",
        summary_ru=summary,
    )

    result = await tts_client.voice_news_item(repo, item_id)
    await db_session.commit()

    mp3_path = news_dir / f"{item_id}.mp3"
    assert mp3_path.is_file()
    assert result.audio_url == f"file://{mp3_path.resolve()}"
    assert result.duration_sec > 0
    assert result.cached is False

    item = await repo.get_by_id(item_id)
    assert item is not None
    assert item.status == NewsItemStatus.READY
    assert item.audio_url == result.audio_url

    probed = probe_duration_sec(mp3_path)
    assert probed == result.duration_sec


@pytest.mark.asyncio
async def test_repeat_summary_skips_second_tts_call(
    tts_client: SaluteSpeechTTS,
    repo: NewsItemRepository,
    db_session: AsyncSession,
    mock_redis: MagicMock,
):
    summary = "Повторяющаяся сводка для проверки Redis-кэша TTS."
    item_a = await _seed_summarized_item(
        repo,
        db_session,
        source_url="https://example.com/tts-a",
        summary_ru=summary,
    )
    item_b = await _seed_summarized_item(
        repo,
        db_session,
        source_url="https://example.com/tts-b",
        summary_ru=summary,
    )

    first = await tts_client.voice_news_item(repo, item_a)
    await db_session.commit()
    assert first.cached is False

    # Only one synthesis HTTP call (oauth may be called once and cached in auth).
    synth_calls = [
        call
        for call in tts_client._client.post.await_args_list
        if "text:synthesize" in str(call.args[0])
    ]
    assert len(synth_calls) == 1

    assert mock_redis._store.get(summary_cache_key(summary)) is not None

    second = await tts_client.voice_news_item(repo, item_b)
    await db_session.commit()
    assert second.cached is True

    synth_calls_after = [
        call
        for call in tts_client._client.post.await_args_list
        if "text:synthesize" in str(call.args[0])
    ]
    assert len(synth_calls_after) == 1
    assert second.audio_url != first.audio_url


def test_committed_stinger_duration_in_range():
    assert STINGER_PATH.is_file(), "data/news/news-stinger.mp3 must be committed"
    duration = probe_duration_sec(STINGER_PATH)
    assert 3.0 <= duration <= 5.0


def test_local_storage_audio_url_pattern(news_dir: Path):
    storage = LocalNewsStorage(news_dir)
    data = b"fake-mp3"
    url = storage.write_item_mp3(42, data)
    assert url == f"file://{(news_dir / '42.mp3').resolve()}"
    assert (news_dir / "42.mp3").read_bytes() == data


def test_wav_to_mp3_roundtrip(news_dir: Path, mock_wav_bytes: bytes):
    mp3_path = news_dir / "roundtrip.mp3"
    wav_bytes_to_mp3(mock_wav_bytes, mp3_path)
    assert mp3_path.is_file()
    assert probe_duration_sec(mp3_path) > 0


def test_summary_cache_key_is_sha256_prefixed():
    text = "тест"
    expected = hashlib.sha256(text.encode("utf-8")).hexdigest()
    assert summary_cache_key(text) == f"fm21:tts:cache:{expected}"


@pytest.mark.asyncio
async def test_auth_token_cached_in_memory():
    http_client = AsyncMock(spec=httpx.AsyncClient)
    response = MagicMock()
    response.status_code = 200
    response.json.return_value = {"access_token": "cached-token", "expires_in": 1800}
    http_client.post.return_value = response

    auth = SaluteSpeechAuth(
        credentials="dGVzdDpzZWNyZXQ=",
        client=http_client,
    )
    first = await auth.get_token()
    second = await auth.get_token()

    assert first == second == "cached-token"
    assert http_client.post.await_count == 1
