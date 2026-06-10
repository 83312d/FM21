"""Yandex Music adapter behind MusicProvider (ADR-002 §2)."""

from __future__ import annotations

import re
from datetime import UTC, datetime, timedelta
from typing import Any, Protocol
from urllib.parse import parse_qs, urlparse

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from yandex_music.exceptions import UnauthorizedError, YandexMusicError

from services.db.models import TrackCache
from services.music.provider import MusicProvider, ProviderUnavailable, StreamUrl, TrackInfo
from services.music.yandex_auth import create_yandex_client

STREAM_URL_REFRESH_BUFFER = timedelta(minutes=2)
_PLAYLIST_ID_RE = re.compile(r"^(?P<uid>\d+):(?P<kind>\d+)$")


class YandexClientProtocol(Protocol):
    async def search(self, text: str, *, type_: str = "track") -> Any: ...

    async def users_playlists(self, kind: int, user_id: int) -> Any: ...

    async def tracks_download_info(
        self, track_id: str | list[str], *, get_direct_links: bool = False
    ) -> list[Any]: ...

    async def tracks(self, track_ids: list[str]) -> list[Any]: ...


def _artist_names(track: Any) -> str:
    artists = getattr(track, "artists", None) or []
    return ", ".join(getattr(artist, "name", "") for artist in artists if getattr(artist, "name", None))


def _duration_sec(track: Any) -> int | None:
    duration_ms = getattr(track, "duration_ms", None)
    if duration_ms is None:
        return None
    return int(duration_ms // 1000)


def _track_info(track: Any) -> TrackInfo:
    track_id = str(getattr(track, "id", ""))
    if not track_id:
        raise ProviderUnavailable("Yandex track is missing id")
    return TrackInfo(
        track_id=track_id,
        title=getattr(track, "title", "") or "Unknown",
        artist=_artist_names(track) or "Unknown",
        duration_sec=_duration_sec(track),
    )


def _parse_playlist_id(playlist_id: str) -> tuple[int, int]:
    match = _PLAYLIST_ID_RE.match(playlist_id.strip())
    if not match:
        raise ProviderUnavailable(
            f"Invalid playlist_id '{playlist_id}'; expected '<uid>:<kind>'"
        )
    return int(match.group("uid")), int(match.group("kind"))


def _expiry_from_url(url: str, *, now: datetime) -> datetime:
    query = parse_qs(urlparse(url).query)
    for key in ("expires", "ts", "et"):
        values = query.get(key)
        if not values:
            continue
        try:
            raw = int(values[0])
            if raw > 10_000_000_000:
                raw //= 1000
            return datetime.fromtimestamp(raw, tz=UTC)
        except (TypeError, ValueError):
            continue
    # Unknown expiry: assume URL is short-lived and refresh soon.
    return now + STREAM_URL_REFRESH_BUFFER


def _pick_download_info(download_info: list[Any]) -> Any:
    if not download_info:
        raise ProviderUnavailable("No download variants available for track")

    mp3_variants = [info for info in download_info if getattr(info, "codec", None) == "mp3"]
    candidates = mp3_variants or download_info
    return max(candidates, key=lambda info: getattr(info, "bitrate_in_kbps", 0) or 0)


class YandexProvider(MusicProvider):
    def __init__(
        self,
        *,
        session: AsyncSession | None = None,
        client: YandexClientProtocol | None = None,
        music_dir: str | None = None,
    ) -> None:
        self._session = session
        self._client = client

    async def _get_client(self) -> YandexClientProtocol:
        if self._client is None:
            self._client = await create_yandex_client()
        return self._client

    async def search(self, query: str, *, limit: int = 10) -> list[TrackInfo]:
        client = await self._get_client()
        try:
            result = await client.search(query, type_="track")
        except UnauthorizedError:
            raise ProviderUnavailable("Yandex Music OAuth token is invalid") from None
        except YandexMusicError:
            raise ProviderUnavailable("Yandex Music search failed") from None

        tracks_block = getattr(result, "tracks", None)
        results = getattr(tracks_block, "results", None) or []
        return [_track_info(track) for track in results[:limit]]

    async def get_playlist_tracks(self, playlist_id: str) -> list[TrackInfo]:
        uid, kind = _parse_playlist_id(playlist_id)
        client = await self._get_client()
        try:
            playlist = await client.users_playlists(kind, uid)
        except UnauthorizedError:
            raise ProviderUnavailable("Yandex Music OAuth token is invalid") from None
        except YandexMusicError:
            raise ProviderUnavailable("Yandex Music playlist fetch failed") from None

        track_shorts = getattr(playlist, "tracks", None) or []
        tracks: list[TrackInfo] = []
        for track_short in track_shorts:
            track = getattr(track_short, "track", None) or track_short
            if track is not None:
                tracks.append(_track_info(track))
        return tracks

    async def _get_cached(self, track_id: str) -> TrackCache | None:
        if self._session is None:
            return None
        return (
            await self._session.execute(
                select(TrackCache).where(TrackCache.yandex_track_id == track_id)
            )
        ).scalar_one_or_none()

    async def _upsert_cache(
        self,
        track_id: str,
        *,
        title: str,
        artist: str,
        stream_url: str,
        expires_at: datetime,
    ) -> None:
        if self._session is None:
            return

        cached = await self._get_cached(track_id)
        if cached is None:
            self._session.add(
                TrackCache(
                    yandex_track_id=track_id,
                    title=title,
                    artist=artist,
                    stream_url=stream_url,
                    stream_url_expires=expires_at,
                )
            )
        else:
            cached.title = title
            cached.artist = artist
            cached.stream_url = stream_url
            cached.stream_url_expires = expires_at
        try:
            await self._session.flush()
        except IntegrityError:
            await self._session.rollback()
            cached = await self._get_cached(track_id)
            if cached is None:
                raise
            cached.title = title
            cached.artist = artist
            cached.stream_url = stream_url
            cached.stream_url_expires = expires_at
            await self._session.flush()

    async def _resolve_from_api(self, track_id: str) -> StreamUrl:
        client = await self._get_client()
        try:
            download_info = await client.tracks_download_info(track_id, get_direct_links=True)
            tracks = await client.tracks([track_id])
        except UnauthorizedError:
            raise ProviderUnavailable("Yandex Music OAuth token is invalid") from None
        except YandexMusicError:
            raise ProviderUnavailable("Yandex Music stream resolution failed") from None

        chosen = _pick_download_info(download_info)
        direct_link = getattr(chosen, "direct_link", None)
        if not direct_link:
            raise ProviderUnavailable("Yandex Music returned no direct stream URL")

        now = datetime.now(UTC)
        expires_at = _expiry_from_url(direct_link, now=now)
        title = "Unknown"
        artist = "Unknown"
        if tracks:
            info = _track_info(tracks[0])
            title = info.title
            artist = info.artist

        await self._upsert_cache(
            track_id,
            title=title,
            artist=artist,
            stream_url=direct_link,
            expires_at=expires_at,
        )
        return StreamUrl(url=direct_link, expires_at=expires_at)

    async def resolve_stream_url(self, track_id: str) -> StreamUrl:
        now = datetime.now(UTC)
        refresh_threshold = now + STREAM_URL_REFRESH_BUFFER
        cached = await self._get_cached(track_id)
        if cached and cached.stream_url_expires > refresh_threshold:
            return StreamUrl(url=cached.stream_url, expires_at=cached.stream_url_expires)
        return await self._resolve_from_api(track_id)
