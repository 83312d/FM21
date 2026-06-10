"""MusicProvider interface and factory (ADR-002, U10)."""

from __future__ import annotations

import logging
import os
from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)


class ProviderUnavailable(Exception):
    """Raised when a music provider cannot serve requests."""


@dataclass(frozen=True, slots=True)
class TrackInfo:
    track_id: str
    title: str
    artist: str
    duration_sec: int | None = None


@dataclass(frozen=True, slots=True)
class StreamUrl:
    url: str
    expires_at: datetime


class MusicProvider(ABC):
    @abstractmethod
    async def search(self, query: str, *, limit: int = 10) -> list[TrackInfo]:
        raise NotImplementedError

    @abstractmethod
    async def get_playlist_tracks(self, playlist_id: str) -> list[TrackInfo]:
        raise NotImplementedError

    @abstractmethod
    async def resolve_stream_url(self, track_id: str) -> StreamUrl:
        raise NotImplementedError


def _static_music_dir() -> str:
    return os.environ.get("STATIC_MUSIC_DIR", "data/music/static")


def get_music_provider(session: AsyncSession | None = None) -> MusicProvider:
    """Return configured provider (sync). Static only — Yandex needs create_music_provider()."""
    from services.music.static_provider import StaticProvider

    provider_name = os.environ.get("MUSIC_PROVIDER", "static").strip().lower()

    if provider_name == "static":
        return StaticProvider(music_dir=_static_music_dir())

    if provider_name == "yandex":
        raise RuntimeError(
            "Yandex provider requires async auth validation; use create_music_provider()"
        )

    raise ValueError(f"Unsupported MUSIC_PROVIDER: {provider_name}")


async def create_music_provider(session: AsyncSession | None = None) -> MusicProvider:
    """Return configured provider with async Yandex auth validation."""
    from services.music.static_provider import StaticProvider
    from services.music.yandex_auth import create_yandex_client
    from services.music.yandex_provider import YandexProvider

    static = StaticProvider(music_dir=_static_music_dir())
    provider_name = os.environ.get("MUSIC_PROVIDER", "static").strip().lower()

    if provider_name == "static":
        return static

    if provider_name == "yandex":
        try:
            client = await create_yandex_client()
            return YandexProvider(
                session=session,
                client=client,
                music_dir=_static_music_dir(),
            )
        except ProviderUnavailable:
            logger.warning("Yandex music unavailable; using static fallback catalog")
            return static

    raise ValueError(f"Unsupported MUSIC_PROVIDER: {provider_name}")
