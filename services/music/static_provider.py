"""Static royalty-free catalog fallback (ADR-002 §1, §4)."""

from __future__ import annotations

import os
from datetime import UTC, datetime, timedelta
from pathlib import Path

from services.music.provider import MusicProvider, ProviderUnavailable, StreamUrl, TrackInfo

_STATIC_URL_TTL = timedelta(days=365)


def _title_from_stem(stem: str) -> str:
    return stem.replace("-", " ").replace("_", " ").title()


class StaticProvider(MusicProvider):
    def __init__(self, music_dir: str | os.PathLike[str]) -> None:
        self._music_dir = Path(music_dir)

    def _tracks(self) -> list[TrackInfo]:
        if not self._music_dir.is_dir():
            return []

        tracks: list[TrackInfo] = []
        for path in sorted(self._music_dir.glob("*.mp3")):
            tracks.append(
                TrackInfo(
                    track_id=path.stem,
                    title=_title_from_stem(path.stem),
                    artist="FM21 Static",
                )
            )
        return tracks

    async def search(self, query: str, *, limit: int = 10) -> list[TrackInfo]:
        needle = query.strip().casefold()
        if not needle:
            return self._tracks()[:limit]

        ranked = [
            track
            for track in self._tracks()
            if needle in track.title.casefold()
            or needle in track.artist.casefold()
            or needle in track.track_id.casefold()
        ]
        return ranked[:limit]

    async def get_playlist_tracks(self, playlist_id: str) -> list[TrackInfo]:
        if playlist_id != "static":
            raise ProviderUnavailable(f"Unknown static playlist: {playlist_id}")
        return self._tracks()

    async def resolve_stream_url(self, track_id: str) -> StreamUrl:
        path = self._music_dir / f"{track_id}.mp3"
        if not path.is_file():
            raise ProviderUnavailable(f"Static track not found: {track_id}")

        uri = path.resolve().as_uri()
        return StreamUrl(url=uri, expires_at=datetime.now(UTC) + _STATIC_URL_TTL)
