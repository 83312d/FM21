"""Yandex MusicProvider tests (U10)."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from sqlalchemy import select
from yandex_music.exceptions import UnauthorizedError

from services.db.migrate import run_migrations
from services.db.models import TrackCache
from services.db.session import async_session_factory, reset_engine
from services.music.provider import ProviderUnavailable, create_music_provider
from services.music.static_provider import StaticProvider
from services.music.yandex_provider import YandexProvider

pytestmark = pytest.mark.asyncio

FIXTURES_DIR = Path(__file__).parent / "fixtures" / "yandex"
STATIC_MUSIC_DIR = Path(__file__).parent.parent / "data" / "music" / "static"


def _load_fixture(name: str) -> dict[str, Any]:
    return json.loads((FIXTURES_DIR / name).read_text(encoding="utf-8"))


def _track_from_dict(data: dict[str, Any]) -> SimpleNamespace:
    return SimpleNamespace(
        id=data["id"],
        title=data["title"],
        duration_ms=data.get("duration_ms"),
        artists=[SimpleNamespace(name=artist["name"]) for artist in data.get("artists", [])],
    )


def _search_result_from_fixture() -> SimpleNamespace:
    payload = _load_fixture("search_tracks.json")
    return SimpleNamespace(
        tracks=SimpleNamespace(
            total=payload["tracks"]["total"],
            results=[_track_from_dict(item) for item in payload["tracks"]["results"]],
        )
    )


def _playlist_from_fixture() -> SimpleNamespace:
    payload = _load_fixture("playlist_tracks.json")
    return SimpleNamespace(
        kind=payload["kind"],
        uid=payload["uid"],
        title=payload["title"],
        tracks=[
            SimpleNamespace(track=_track_from_dict(item["track"])) for item in payload["tracks"]
        ],
    )


def _download_info_from_fixture(expires: int | None = None) -> list[SimpleNamespace]:
    payload = _load_fixture("download_info.json")
    items: list[SimpleNamespace] = []
    for entry in payload:
        link = entry["direct_link"]
        if expires is not None:
            link = f"https://cdn.example/yandex/track.mp3?expires={expires}"
        items.append(
            SimpleNamespace(
                codec=entry["codec"],
                bitrate_in_kbps=entry["bitrate_in_kbps"],
                direct_link=link,
            )
        )
    return items


@dataclass
class FakeYandexClient:
    search_result: Any | None = None
    playlist: Any | None = None
    download_info: list[Any] | None = None
    tracks_result: list[Any] | None = None
    search_error: Exception | None = None
    download_error: Exception | None = None

    async def search(self, text: str, *, type_: str = "track") -> Any:
        if self.search_error:
            raise self.search_error
        return self.search_result or _search_result_from_fixture()

    async def users_playlists(self, kind: int, user_id: int) -> Any:
        return self.playlist or _playlist_from_fixture()

    async def tracks_download_info(
        self, track_id: str | list[str], *, get_direct_links: bool = False
    ) -> list[Any]:
        if self.download_error:
            raise self.download_error
        return self.download_info or _download_info_from_fixture()

    async def tracks(self, track_ids: list[str]) -> list[Any]:
        if self.tracks_result is not None:
            return self.tracks_result
        payload = _load_fixture("search_tracks.json")
        return [_track_from_dict(payload["tracks"]["results"][0])]


@pytest.fixture(autouse=True)
def _reset_engine():
    reset_engine()
    yield
    reset_engine()


@pytest.fixture
async def migrated_db():
    await run_migrations()
    yield
    from services.db.session import get_engine
    from sqlalchemy import text

    engine = get_engine()
    async with engine.begin() as conn:
        await conn.execute(text("TRUNCATE TABLE tracks_cache RESTART IDENTITY CASCADE"))


@pytest.fixture
async def db_session(migrated_db):
    async with async_session_factory()() as session:
        yield session


@pytest.fixture
def yandex_client() -> FakeYandexClient:
    return FakeYandexClient()


@pytest.fixture
def yandex_provider(db_session, yandex_client: FakeYandexClient) -> YandexProvider:
    return YandexProvider(
        session=db_session,
        client=yandex_client,
        music_dir=str(STATIC_MUSIC_DIR),
    )


async def test_search_returns_ranked_tracks(yandex_provider: YandexProvider):
    results = await yandex_provider.search("Queen", limit=2)

    assert len(results) == 2
    assert results[0].track_id == "1001"
    assert results[0].title == "Bohemian Rhapsody"
    assert results[0].artist == "Queen"
    assert results[0].duration_sec == 354
    assert results[1].track_id == "1002"


async def test_get_playlist_tracks(yandex_provider: YandexProvider):
    tracks = await yandex_provider.get_playlist_tracks("12345:3")

    assert [track.track_id for track in tracks] == ["2001", "2002"]
    assert tracks[0].title == "Track One"
    assert tracks[1].artist == "Artist B"


async def test_resolve_stream_url_caches_result(yandex_provider: YandexProvider, db_session):
    stream = await yandex_provider.resolve_stream_url("1001")

    assert stream.url.endswith("track-1001-hq.mp3?expires=1893456000")
    assert stream.expires_at == datetime.fromtimestamp(1893456000, tz=UTC)

    cached = (
        await db_session.execute(
            select(TrackCache).where(TrackCache.yandex_track_id == "1001")
        )
    ).scalar_one()
    assert cached.title == "Bohemian Rhapsody"
    assert cached.stream_url == stream.url


async def test_expired_url_triggers_reresolve(
    yandex_provider: YandexProvider,
    yandex_client: FakeYandexClient,
    db_session,
):
    stale_expires = datetime.now(UTC) + timedelta(seconds=30)
    db_session.add(
        TrackCache(
            yandex_track_id="1001",
            title="Stale",
            artist="Stale Artist",
            stream_url="https://cdn.example/stale.mp3",
            stream_url_expires=stale_expires,
        )
    )
    await db_session.commit()

    new_expires = int((datetime.now(UTC) + timedelta(hours=2)).timestamp())
    yandex_client.download_info = _download_info_from_fixture(expires=new_expires)

    stream = await yandex_provider.resolve_stream_url("1001")

    assert stream.url == f"https://cdn.example/yandex/track.mp3?expires={new_expires}"
    refreshed = (
        await db_session.execute(
            select(TrackCache).where(TrackCache.yandex_track_id == "1001")
        )
    ).scalar_one()
    assert refreshed.stream_url == stream.url
    assert refreshed.title == "Bohemian Rhapsody"


async def test_invalid_token_raises_provider_unavailable(yandex_provider: YandexProvider):
    yandex_provider._client = FakeYandexClient(search_error=UnauthorizedError("invalid token"))

    with pytest.raises(ProviderUnavailable, match="invalid"):
        await yandex_provider.search("Queen")


async def test_invalid_token_factory_falls_back_to_static(
    monkeypatch: pytest.MonkeyPatch,
    db_session,
):
    monkeypatch.setenv("MUSIC_PROVIDER", "yandex")
    monkeypatch.setenv("YANDEX_MUSIC_OAUTH_TOKEN", "bad-token")
    monkeypatch.setenv("STATIC_MUSIC_DIR", str(STATIC_MUSIC_DIR))

    async def _raise_invalid(*_args, **_kwargs):
        raise ProviderUnavailable("Yandex Music OAuth token is invalid")

    monkeypatch.setattr("services.music.yandex_auth.create_yandex_client", _raise_invalid)

    provider = await create_music_provider(session=db_session)

    assert isinstance(provider, StaticProvider)
    tracks = await provider.search("bed")
    assert any(track.track_id.startswith("bed-") for track in tracks)


async def test_static_provider_reads_seed_catalog(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("STATIC_MUSIC_DIR", str(STATIC_MUSIC_DIR))
    provider = StaticProvider(music_dir=STATIC_MUSIC_DIR)

    tracks = await provider.get_playlist_tracks("static")
    assert len(tracks) >= 5
    assert all(track.artist == "FM21 Static" for track in tracks)

    stream = await provider.resolve_stream_url(tracks[0].track_id)
    assert stream.url.startswith("file://")
    assert stream.url.endswith(f"{tracks[0].track_id}.mp3")
