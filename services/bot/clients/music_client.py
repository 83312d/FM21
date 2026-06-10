"""Music catalog search and stream resolution for bot /order."""

from __future__ import annotations

from services.music.provider import StreamUrl, TrackInfo, create_music_provider


async def search_tracks(query: str, *, limit: int = 3) -> list[TrackInfo]:
    provider = await create_music_provider()
    return await provider.search(query, limit=limit)


async def resolve_stream_url(track_id: str) -> StreamUrl:
    provider = await create_music_provider()
    return await provider.resolve_stream_url(track_id)
