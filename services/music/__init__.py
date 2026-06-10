"""Music catalog providers (U10)."""

from services.music.provider import (
    MusicProvider,
    ProviderUnavailable,
    StreamUrl,
    TrackInfo,
    create_music_provider,
    get_music_provider,
)

__all__ = [
    "MusicProvider",
    "ProviderUnavailable",
    "StreamUrl",
    "TrackInfo",
    "create_music_provider",
    "get_music_provider",
]
